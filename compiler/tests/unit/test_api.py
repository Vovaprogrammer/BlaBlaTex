"""Проверка запроса до запуска TeX: без Docker, на любой ОС."""

import asyncio
import io
import os
import tarfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app import main as main_module
from app.archive import MB
from app.main import create_app
from app.runner import RunResult
from tests.support import make_tar


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://compiler") as ac:
        yield ac


async def post_compile(
    client: AsyncClient, archive: bytes | None = None, **fields: str
) -> Response:
    files = {"archive": ("project.tar.gz", archive, "application/gzip")} if archive else None
    return await client.post("/compile", files=files, data=fields)


# Any: элементы details.errors — JSON со строками и списками.
def field_errors(response: Response) -> list[dict[str, Any]]:
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    return error["details"]["errors"]


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_archive_is_required(client: AsyncClient) -> None:
    errors = field_errors(await post_compile(client, main="main.tex"))

    assert errors == [
        {"loc": ["body", "archive"], "type": "missing", "message": "Обязательное поле"}
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("engine", "luatex"),
        # LuaLaTeX не работает при openin_any=p (architecture.md, раздел 6).
        ("engine", "lualatex"),
        ("engine", "xelatex -shell-escape"),
        ("timeout_s", "0"),
        ("timeout_s", "121"),
        ("timeout_s", "abc"),
    ],
)
async def test_rejects_bad_fields(client: AsyncClient, field: str, value: str) -> None:
    response = await post_compile(client, make_tar({"main.tex": ""}), **{field: value})

    assert [error["loc"] for error in field_errors(response)] == [["body", field]]


@pytest.mark.parametrize(
    "main",
    [
        "-e.tex",
        "../main.tex",
        "/main.tex",
        "main.txt",
        "main",
        "a\\main.tex",
        # latexmk передаёт имя в shell в двойных кавычках — там это выполнилось бы.
        "x`id`.tex",
        "x$(id).tex",
        'x".tex',
        "отчёт (1).tex",
    ],
)
async def test_rejects_bad_main(client: AsyncClient, main: str) -> None:
    response = await post_compile(client, make_tar({"main.tex": ""}), main=main)

    [error] = field_errors(response)
    assert (error["loc"], error["type"]) == (["body", "main"], "invalid_main")


@pytest.mark.parametrize("main", ["report.tex", "отчёт по ЛР 1.tex", "lab_1/main-v2.tex"])
async def test_main_must_be_in_archive(client: AsyncClient, main: str) -> None:
    # Имя подходит, но такого файла в архиве нет.
    response = await post_compile(client, make_tar({"main.tex": ""}), main=main)

    [error] = field_errors(response)
    assert (error["loc"], error["type"]) == (["body", "main"], "main_not_found")


async def test_rejects_archive_with_out_folder(client: AsyncClient) -> None:
    archive = make_tar({"main.tex": "", "out/main.pdf": b"%PDF-forged"})

    [error] = field_errors(await post_compile(client, archive))

    assert (error["loc"], error["type"]) == (["body", "archive"], "reserved_path")


async def test_rejects_not_tar_gz(client: AsyncClient) -> None:
    [error] = field_errors(await post_compile(client, b"definitely not an archive"))

    assert (error["loc"], error["type"]) == (["body", "archive"], "invalid_archive")


async def test_rejects_archive_with_symlink(client: AsyncClient) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        link = tarfile.TarInfo("main.tex")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)

    [error] = field_errors(await post_compile(client, buffer.getvalue()))

    assert error["type"] == "invalid_archive"
    assert "ссылка" in error["message"]


async def test_rejects_too_many_files(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.archive.MAX_FILES", 1)

    response = await post_compile(client, make_tar({"main.tex": "", "other.tex": ""}))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_rejects_body_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Лимит тела — размер архива плюс 1 МБ на заголовки формы.
    monkeypatch.setattr(main_module, "MAX_ARCHIVE_BYTES", 0)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://compiler") as client:
        response = await post_compile(client, os.urandom(2 * MB))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_rejects_streamed_body_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Без Content-Length (chunked) лимит срабатывает по мере чтения тела.
    monkeypatch.setattr(main_module, "MAX_ARCHIVE_BYTES", 0)

    async def body() -> AsyncIterator[bytes]:
        yield (
            b'--x\r\nContent-Disposition: form-data; name="archive"; filename="p.tar.gz"\r\n'
            b"Content-Type: application/gzip\r\n\r\n"
        )
        for _ in range(3):
            yield os.urandom(MB)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://compiler") as client:
        response = await client.post(
            "/compile", content=body(), headers={"content-type": "multipart/form-data; boundary=x"}
        )

    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_parallel_builds_are_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    running = peak = 0

    async def fake_run(
        workdir: Path, console: Path, engine: str, main: str, timeout_s: int
    ) -> RunResult:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return RunResult("error", 1, 50)

    monkeypatch.setattr(main_module, "run_latexmk", fake_run)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://compiler") as client:
        archive = make_tar({"main.tex": ""})
        responses = await asyncio.gather(*(post_compile(client, archive) for _ in range(5)))

    assert [response.status_code for response in responses] == [200] * 5
    assert peak == main_module.MAX_PARALLEL_BUILDS


async def test_unknown_path_uses_error_format(client: AsyncClient) -> None:
    response = await client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
