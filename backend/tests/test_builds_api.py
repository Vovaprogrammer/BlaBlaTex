"""Эндпоинты сборок: запуск, статус, последняя сборка, PDF и лог, чужие сборки.

Компилятор подменён (tests/fake_compiler.py), хранилище — во временной папке из настроек.
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.storage import LocalStorage
from app.modules.builds.dependencies import get_compiler
from tests.fake_compiler import LOG, PDF, FakeCompiler
from tests.helpers import CSRF, SignUp

MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nПривет\n\\end{document}\n"


@pytest.fixture
def fake(app: FastAPI) -> FakeCompiler:
    """Подменный компилятор вместо клиента из lifespan."""
    fake = FakeCompiler()
    client = fake.client()
    app.dependency_overrides[get_compiler] = lambda: client
    return fake


@pytest.fixture
async def lab(user_client: AsyncClient, project: dict[str, Any]) -> str:
    """id проекта студента с main.tex."""
    pid = project["id"]
    await write(user_client, pid, "main.tex", MAIN_TEX)
    return pid


async def write(client: AsyncClient, pid: str, path: str, text: str) -> None:
    response = await client.put(f"/api/v1/projects/{pid}/files/{path}", content=text)
    assert response.status_code in (200, 201), response.text


async def start(client: AsyncClient, pid: str) -> dict[str, Any]:
    response = await client.post(f"/api/v1/projects/{pid}/builds")
    assert response.status_code == 201, response.text
    return response.json()


async def test_build_returns_status_and_pdf_flag(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    build = await start(user_client, lab)

    assert build | {"id": None, "created_at": None, "duration_ms": None} == {
        "id": None,
        "project_id": lab,
        "status": "ok",
        "engine": "xelatex",
        "pages": 1,
        "duration_ms": None,
        "warnings_count": 0,
        "errors": [],
        "has_pdf": True,
        "created_at": None,
    }
    assert build["duration_ms"] == 1500


async def test_get_build_matches_start_response(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    build = await start(user_client, lab)

    response = await user_client.get(f"/api/v1/builds/{build['id']}")

    assert response.status_code == 200
    assert response.json() == build


async def test_pdf_is_served_as_pdf(user_client: AsyncClient, fake: FakeCompiler, lab: str) -> None:
    build = await start(user_client, lab)

    response = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'inline; filename="build-{build["id"]}.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == PDF


async def test_log_is_served_as_text(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    build = await start(user_client, lab)

    response = await user_client.get(f"/api/v1/builds/{build['id']}/log")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    # Лог — текст пользователя: браузер не должен принять его за HTML.
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == LOG


async def test_latex_errors_are_build_status_not_http_error(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 700}
    fake.files = {
        "output.log": b"(./main.tex\n./main.tex:3: Undefined control sequence.\nl.3 \\foo\n"
        b"LaTeX Warning: Reference `x' on page 1 undefined on input line 3.\n\n)\n"
    }

    build = await start(user_client, lab)

    assert (build["status"], build["has_pdf"], build["pages"]) == ("error", False, None)
    assert build["warnings_count"] == 1
    assert [(e["file"], e["line"], e["severity"]) for e in build["errors"]] == [
        ("main.tex", 3, "error"),
        ("main.tex", 3, "warning"),
    ]
    assert build["errors"][0]["message"] == "Undefined control sequence: \\foo"
    assert "> 3 | Привет" in build["errors"][0]["context"]
    pdf = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")
    assert pdf.status_code == 404
    assert pdf.json()["error"]["message"] == "У этой сборки нет PDF"


async def test_project_problem_is_error_build_without_log(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    await write(user_client, lab, "out/old.tex", "старый результат")

    build = await start(user_client, lab)

    assert build["status"] == "error"
    assert "Папка out/ в корне проекта занята" in build["errors"][0]["message"]
    assert fake.requests == []
    log = await user_client.get(f"/api/v1/builds/{build['id']}/log")
    assert log.status_code == 404


async def test_latest_build_is_404_before_first_build(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    response = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Проект ещё не собирали",
        "details": {},
    }


async def test_latest_build_is_last_started(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    await start(user_client, lab)
    await write(user_client, lab, "main.tex", MAIN_TEX.replace("Привет", "\\foo"))
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 700}
    failed = await start(user_client, lab)

    response = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")

    assert response.json() == failed


async def test_rebuild_without_changes_comes_from_cache(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    first = await start(user_client, lab)
    second = await start(user_client, lab)

    assert len(fake.requests) == 1
    assert second["id"] != first["id"]
    assert (second["status"], second["has_pdf"]) == ("ok", True)
    latest = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")
    assert latest.json()["id"] == second["id"]
    pdf = await user_client.get(f"/api/v1/builds/{second['id']}/pdf")
    assert pdf.content == PDF


async def test_pdf_gone_from_storage_is_404(
    app: FastAPI, user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    build = await start(user_client, lab)
    storage: LocalStorage = app.state.storage
    for path in storage.root.rglob("*"):
        if path.is_file():
            path.unlink()

    response = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Файл сборки не найден. Соберите проект ещё раз."


async def test_compiler_unavailable_is_500_without_build(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    fake.error = httpx.ConnectError("refused")

    response = await user_client.post(f"/api/v1/projects/{lab}/builds")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal",
        "message": "Сервис сборки сейчас недоступен. Попробуйте через минуту.",
        "details": {},
    }
    latest = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")
    assert latest.status_code == 404


async def test_someone_elses_builds_are_not_found(
    user_client: AsyncClient, sign_up: SignUp, fake: FakeCompiler, lab: str
) -> None:
    build = await start(user_client, lab)
    await sign_up("petrov@example.com")
    user_client.headers.update(CSRF)

    urls = [
        ("POST", f"/api/v1/projects/{lab}/builds"),
        ("GET", f"/api/v1/projects/{lab}/builds/latest"),
        ("GET", f"/api/v1/builds/{build['id']}"),
        ("GET", f"/api/v1/builds/{build['id']}/pdf"),
        ("GET", f"/api/v1/builds/{build['id']}/log"),
    ]
    for method, url in urls:
        response = await user_client.request(method, url)
        assert response.status_code == 404, url
    assert len(fake.requests) == 1


async def test_unknown_build_is_not_found(user_client: AsyncClient, fake: FakeCompiler) -> None:
    response = await user_client.get("/api/v1/builds/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Сборка не найдена"


async def test_builds_need_sign_in(db_client: AsyncClient, fake: FakeCompiler, lab: str) -> None:
    db_client.cookies.clear()

    response = await db_client.get(f"/api/v1/projects/{lab}/builds/latest")

    assert response.status_code == 401
