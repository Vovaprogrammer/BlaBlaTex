"""HTTP-часть SyncTeX компилятора: поля, ошибки и очередь. Без Docker, на любой ОС."""

import asyncio
import gzip
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app import main as main_module
from app import synctex as synctex_module
from app.main import create_app
from app.runner import RunResult
from app.synctex import SyncTexRunError
from tests.support import make_tar

SYNCTEX = b"""SyncTeX Version:1
Input:1:/tmp/job-abc123/src/./main.tex
Content:
{1
[1,9:0,47949085:32557311,47949085,0
(1,4:857753,100953:31699558,1107880,474813
)
]
}1
Postamble:
"""
SYNCTEX_GZ = gzip.compress(SYNCTEX)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://compiler") as ac:
        yield ac


def answer_with(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, str]]) -> list[Path]:
    """Вместо программы synctex — готовые записи ответа. Возвращает рабочие папки вызовов."""
    workdirs: list[Path] = []

    async def fake_run(workdir: Path, *args: str) -> list[dict[str, str]]:
        workdirs.append(workdir)
        return records

    monkeypatch.setattr(synctex_module, "run_synctex", fake_run)
    return workdirs


async def post(
    client: AsyncClient, kind: str, synctex: bytes | None = SYNCTEX_GZ, **fields: str
) -> Response:
    files = {"synctex": ("output.synctex.gz", synctex, "application/gzip")} if synctex else None
    return await client.post(f"/synctex/{kind}", files=files, data=fields)


# Any: элементы details.errors — JSON со строками и списками.
def field_errors(response: Response) -> list[dict[str, Any]]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("validation_error", "Неверный запрос SyncTeX")
    return error["details"]["errors"]


async def test_edit_answers_project_line(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer_with(monkeypatch, [{"Input": "main.tex", "Line": "4", "Column": "-1"}])

    response = await post(client, "edit", page="1", x="300", y="70.5")

    assert response.status_code == 200
    assert response.json() == {"source": {"path": "main.tex", "line": 4}}


async def test_edit_answers_null_where_page_was_shipped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer_with(monkeypatch, [{"Input": "/blablatex/page", "Line": "9"}])

    response = await post(client, "edit", page="1", x="326", y="797")

    assert response.json() == {"source": None}


async def test_view_answers_boxes(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    record = {"Page": "1", "h": "85.04", "v": "133.57", "W": "481.89", "H": "12.49"}
    answer_with(monkeypatch, [record, record])

    response = await post(client, "view", path="main.tex", line="4")

    assert response.status_code == 200
    assert response.json() == {
        "boxes": [{"page": 1, "x": 85.04, "y": 121.08, "width": 481.89, "height": 12.49}]
    }


@pytest.mark.parametrize(
    ("kind", "fields"),
    [("edit", {"page": "1", "x": "1", "y": "1"}), ("view", {"path": "main.tex", "line": "1"})],
)
async def test_synctex_file_is_required(
    client: AsyncClient, kind: str, fields: dict[str, str]
) -> None:
    errors = field_errors(await post(client, kind, None, **fields))

    assert [error["loc"] for error in errors] == [["body", "synctex"]]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page", "0"),
        ("page", "abc"),
        ("x", "-1"),
        ("x", "14400.5"),
        ("x", "nan"),
        ("y", "inf"),
        ("y", "abc"),
    ],
)
async def test_edit_rejects_bad_fields(client: AsyncClient, field: str, value: str) -> None:
    fields = {"page": "1", "x": "1", "y": "1", field: value}

    errors = field_errors(await post(client, "edit", **fields))

    assert [error["loc"] for error in errors] == [["body", field]]


@pytest.mark.parametrize("line", ["0", "10000001", "abc"])
async def test_view_rejects_bad_line(client: AsyncClient, line: str) -> None:
    errors = field_errors(await post(client, "view", path="main.tex", line=line))

    assert [error["loc"] for error in errors] == [["body", "line"]]


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../main.tex",
        "/tmp/job-1/src/main.tex",
        "sections/../main.tex",
        "./main.tex",
        # Двоеточие разделяет поля в аргументе -i строка:столбец:файл.
        "5:0:main.tex",
        "a\\b.tex",
        "a//b.tex",
        "line\nbreak.tex",
        "a" * 256,
    ],
)
async def test_view_rejects_bad_path(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    workdirs = answer_with(monkeypatch, [])

    errors = field_errors(await post(client, "view", path=path, line="1"))

    assert [error["loc"] for error in errors] == [["body", "path"]]
    assert workdirs == []


@pytest.mark.parametrize("data", [b"not gzip", gzip.compress(b"%PDF-1.7\n")])
async def test_rejects_file_that_is_not_synctex(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, data: bytes
) -> None:
    workdirs = answer_with(monkeypatch, [])

    [error] = field_errors(await post(client, "edit", data, page="1", x="1", y="1"))

    assert (error["loc"], error["type"]) == (["body", "synctex"], "invalid_synctex")
    assert workdirs == []


async def test_rejects_too_large_file(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "MAX_SYNCTEX_BYTES", len(SYNCTEX_GZ) - 1)

    response = await post(client, "view", path="main.tex", line="1")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_rejects_too_large_unpacked_file(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(synctex_module, "MAX_SYNCTEX_BYTES", len(SYNCTEX) - 1)
    answer_with(monkeypatch, [])

    response = await post(client, "edit", page="1", x="1", y="1")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_synctex_failure_is_internal_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_run(workdir: Path, *args: str) -> list[dict[str, str]]:
        raise SyncTexRunError("synctex не ответил за 10 с")

    monkeypatch.setattr(synctex_module, "run_synctex", failing_run)

    response = await post(client, "view", path="main.tex", line="1")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal"


async def test_synctex_does_not_wait_for_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    building = 0

    async def endless_build(
        workdir: Path, console: Path, engine: str, main: str, timeout_s: int
    ) -> RunResult:
        nonlocal building
        building += 1
        if building == main_module.MAX_PARALLEL_BUILDS:
            started.set()
        await release.wait()
        return RunResult("error", 1, 50)

    monkeypatch.setattr(main_module, "run_latexmk", endless_build)
    answer_with(monkeypatch, [{"Input": "main.tex", "Line": "4"}])
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://compiler") as client:
        archive = make_tar({"main.tex": ""})
        builds = [
            asyncio.create_task(client.post("/compile", files={"archive": ("p.tar.gz", archive)}))
            for _ in range(main_module.MAX_PARALLEL_BUILDS + 1)
        ]
        await asyncio.wait_for(started.wait(), 5)

        response = await asyncio.wait_for(post(client, "edit", page="1", x="1", y="1"), 5)

        assert response.json() == {"source": {"path": "main.tex", "line": 4}}
        assert not any(build.done() for build in builds)
        release.set()
        assert [(await build).status_code for build in builds] == [200] * len(builds)


async def test_parallel_synctex_queries_are_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    running = peak = 0

    async def slow_run(workdir: Path, *args: str) -> list[dict[str, str]]:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return []

    monkeypatch.setattr(synctex_module, "run_synctex", slow_run)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://compiler") as client:
        responses = await asyncio.gather(
            *(post(client, "view", path="main.tex", line="1") for _ in range(5))
        )

    assert [response.status_code for response in responses] == [200] * 5
    assert peak == main_module.MAX_PARALLEL_SYNCTEX
