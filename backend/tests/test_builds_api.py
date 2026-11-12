"""Эндпоинты сборок: постановка в очередь, статус, последняя сборка, PDF и лог, чужие сборки.

POST /builds только ставит сборку в очередь (9.1); собирает воркер из tests/build_worker.py
с подменным компилятором (tests/fake_compiler.py). Хранилище — во временной папке.
"""

import uuid
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq.exceptions import SendTaskError

from app.core.errors import INTERNAL_MESSAGE
from app.core.events import BuildFinishedData, BuildStartedData
from app.core.storage import LocalStorage
from app.modules.builds import service as builds_service
from app.modules.builds.dependencies import get_enqueue
from app.modules.builds.models import Build
from app.modules.builds.router import BUILDS_LIMIT
from tests.build_worker import BuildWorker
from tests.fake_compiler import LOG, PDF, FakeCompiler
from tests.fake_events import FakeEvents
from tests.fake_rate_limiter import FakeRateLimiter, RateCheck
from tests.helpers import CSRF, SignUp, set_last_name
from tests.test_bearer_auth import issue_token, use_token

MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nПривет\n\\end{document}\n"
# Any в этом файле — проект и сборка как JSON из ответа API.


@pytest.fixture
def fake(build_worker: BuildWorker) -> FakeCompiler:
    """Подменный компилятор воркера сборок."""
    return build_worker.fake


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
    assert response.status_code == 202, response.text
    return response.json()


async def built(client: AsyncClient, worker: BuildWorker, pid: str) -> dict[str, Any]:
    """Ставит сборку в очередь, даёт воркеру её собрать и возвращает итог из GET."""
    queued = await start(client, pid)
    await worker.run()
    response = await client.get(f"/api/v1/builds/{queued['id']}")
    assert response.status_code == 200, response.text
    return response.json()


# Очередь.


async def test_build_is_queued_and_answer_comes_at_once(
    user_client: AsyncClient, build_worker: BuildWorker, lab: str
) -> None:
    build = await start(user_client, lab)

    assert build | {"id": None, "created_at": None} == {
        "id": None,
        "project_id": lab,
        "status": "queued",
        "engine": "xelatex",
        "pages": None,
        "duration_ms": None,
        "warnings_count": 0,
        "errors": [],
        "has_pdf": False,
        "created_at": None,
    }
    assert [str(build_id) for build_id in build_worker.queued] == [build["id"]]
    assert build_worker.fake.requests == []


async def test_second_request_while_queued_returns_same_build(
    user_client: AsyncClient, build_worker: BuildWorker, lab: str
) -> None:
    first = await start(user_client, lab)

    second = await start(user_client, lab)

    assert second == first
    # Воркер разбужен один раз: второй раз сборку собирать не нужно.
    assert len(build_worker.queued) == 1


async def test_queue_unavailable_is_500_without_build(
    app: FastAPI, user_client: AsyncClient, lab: str
) -> None:
    async def unavailable(build_id: object) -> None:
        raise SendTaskError

    app.dependency_overrides[get_enqueue] = lambda: unavailable

    response = await user_client.post(f"/api/v1/projects/{lab}/builds")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal",
        "message": "Сервис сборки сейчас недоступен. Попробуйте через минуту.",
        "details": {},
    }
    latest = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")
    assert latest.status_code == 404


async def test_builds_are_rate_limited_per_student(
    user_client: AsyncClient, lab: str, rate_limits: FakeRateLimiter
) -> None:
    me = (await user_client.get("/api/v1/auth/me")).json()["user"]["id"]
    rate_limits.retry_after = 42

    response = await user_client.post(f"/api/v1/projects/{lab}/builds")

    assert response.status_code == 429
    assert response.json()["error"]["message"] == "Слишком много запросов. Повторите через 42 с"
    assert response.headers["Retry-After"] == "42"
    assert rate_limits.checks[-1] == RateCheck("builds", me, BUILDS_LIMIT)
    assert (BUILDS_LIMIT.count, BUILDS_LIMIT.period_s) == (60, 600)
    latest = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")
    assert latest.status_code == 404


async def test_build_by_token_counts_for_its_owner(
    user_client: AsyncClient, lab: str, build_worker: BuildWorker, rate_limits: FakeRateLimiter
) -> None:
    me = (await user_client.get("/api/v1/auth/me")).json()["user"]["id"]
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    await start(user_client, lab)

    assert rate_limits.checks[-1] == RateCheck("builds", me, BUILDS_LIMIT)


# Итог сборки.


async def test_storage_failure_ends_build_with_error(
    app: FastAPI,
    user_client: AsyncClient,
    build_worker: BuildWorker,
    fake: FakeCompiler,
    lab: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def full_disk(data: bytes) -> str:
        raise OSError("No space left on device")

    monkeypatch.setattr(app.state.storage, "put", full_disk)

    build = await built(user_client, build_worker, lab)

    # Сборка не висит «идущей» до проверки зависших, а заканчивается ошибкой.
    assert build["status"] == "error"
    assert build["has_pdf"] is False
    assert build["errors"][0]["message"] == INTERNAL_MESSAGE


async def test_worker_result_has_status_and_pdf_flag(
    user_client: AsyncClient, build_worker: BuildWorker, lab: str
) -> None:
    build = await built(user_client, build_worker, lab)

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


async def test_get_build_follows_status(
    user_client: AsyncClient, build_worker: BuildWorker, lab: str
) -> None:
    queued = await start(user_client, lab)
    waiting = await user_client.get(f"/api/v1/builds/{queued['id']}")
    await build_worker.run()

    finished = await user_client.get(f"/api/v1/builds/{queued['id']}")

    assert waiting.json() == queued
    assert finished.json()["id"] == queued["id"]
    assert finished.json()["status"] == "ok"


async def test_pdf_is_served_as_pdf(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    build = await built(user_client, build_worker, lab)

    response = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    # Фамилии в профиле нет — имя из вида работы и номера (9.1, «Имя отчёта»).
    assert response.headers["content-disposition"] == pdf_disposition("ЛР1.pdf")
    assert response.headers["x-content-type-options"] == "nosniff"
    # Встраивать PDF может только наш сайт; CSP нет — он мешал бы просмотрщику PDF браузера.
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "content-security-policy" not in response.headers
    assert "cache-control" not in response.headers
    assert response.content == PDF


def pdf_disposition(name: str) -> str:
    fallback = "".join(char if char.isascii() else "_" for char in name)
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


async def pdf_name(client: AsyncClient, build: dict[str, Any]) -> str:
    response = await client.get(f"/api/v1/builds/{build['id']}/pdf")
    assert response.status_code == 200, response.text
    return response.headers["content-disposition"]


async def test_pdf_is_named_by_work_and_last_name(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    await set_last_name(user_client, "Чистяков")
    build = await built(user_client, build_worker, lab)

    assert await pdf_name(user_client, build) == pdf_disposition("ЛР1_Чистяков.pdf")


async def test_pdf_keeps_name_from_build_time(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    """Номер поменяли после сборки: старый PDF — с прежним номером, как у него на титуле."""
    await set_last_name(user_client, "Чистяков")
    first = await built(user_client, build_worker, lab)

    fields = {"lab_number": 4, "lab_title": "Сортировки"}
    response = await user_client.patch(f"/api/v1/projects/{lab}", json={"fields": fields})
    assert response.status_code == 200, response.text
    await set_last_name(user_client, "Петров")

    assert await pdf_name(user_client, first) == pdf_disposition("ЛР1_Чистяков.pdf")
    second = await built(user_client, build_worker, lab)
    assert await pdf_name(user_client, second) == pdf_disposition("ЛР4_Петров.pdf")


async def test_build_before_names_uses_current_data(
    user_client: AsyncClient,
    db_session: AsyncSession,
    build_worker: BuildWorker,
    fake: FakeCompiler,
    lab: str,
) -> None:
    build = await built(user_client, build_worker, lab)
    await db_session.execute(
        update(Build).where(Build.id == uuid.UUID(build["id"])).values(pdf_name=None)
    )
    await set_last_name(user_client, "Чистяков")

    assert await pdf_name(user_client, build) == pdf_disposition("ЛР1_Чистяков.pdf")


async def test_old_build_of_deleted_project_has_no_name(db_session: AsyncSession) -> None:
    """Проект удалили между проверкой доступа и подсчётом имени — None, маршрут отдаст 404."""
    orphan = Build(project_id=uuid.uuid4(), status="ok", engine="xelatex")

    assert await builds_service.legacy_pdf_name(db_session, orphan) is None


async def test_agent_downloads_pdf_by_token(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    await set_last_name(user_client, "Чистяков")
    build = await built(user_client, build_worker, lab)
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    response = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-disposition"] == pdf_disposition("ЛР1_Чистяков.pdf")


async def test_log_is_served_as_text(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    build = await built(user_client, build_worker, lab)

    response = await user_client.get(f"/api/v1/builds/{build['id']}/log")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    # Лог — текст пользователя: браузер не должен принять его за HTML.
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == LOG


async def test_build_is_announced_when_it_starts_and_when_it_ends(
    user_client: AsyncClient, build_worker: BuildWorker, lab: str, events: FakeEvents
) -> None:
    events.published.clear()

    queued = await start(user_client, lab)
    # В очереди — без события: «в очереди» видит вкладка, которая нажала «Собрать».
    assert events.published == []
    await build_worker.run()

    build = (await user_client.get(f"/api/v1/builds/{queued['id']}")).json()
    build_id = uuid.UUID(build["id"])
    assert all(event.project_id == uuid.UUID(lab) for event in events.published)
    assert [event.data for event in events.published] == [
        BuildStartedData(build_id=build_id),
        BuildFinishedData(build_id=build_id, status="ok", pages=build["pages"], errors_count=0),
    ]


async def test_latex_errors_are_build_status_not_http_error(
    user_client: AsyncClient,
    build_worker: BuildWorker,
    fake: FakeCompiler,
    lab: str,
    events: FakeEvents,
) -> None:
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 700}
    fake.files = {
        "output.log": b"(./main.tex\n./main.tex:3: Undefined control sequence.\nl.3 \\foo\n"
        b"LaTeX Warning: Reference `x' on page 1 undefined on input line 3.\n\n)\n"
    }

    build = await built(user_client, build_worker, lab)

    assert (build["status"], build["has_pdf"], build["pages"]) == ("error", False, None)
    assert build["warnings_count"] == 1
    assert [(e["file"], e["line"], e["severity"]) for e in build["errors"]] == [
        ("main.tex", 3, "error"),
        ("main.tex", 3, "warning"),
    ]
    assert build["errors"][0]["message"] == "Undefined control sequence: \\foo"
    # Вкладкам — число ошибок без предупреждений.
    finished = events.published[-1].data
    assert isinstance(finished, BuildFinishedData)
    assert (finished.status, finished.pages, finished.errors_count) == ("error", None, 1)
    assert "> 3 | Привет" in build["errors"][0]["context"]
    pdf = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")
    assert pdf.status_code == 404
    assert pdf.json()["error"]["message"] == "У этой сборки нет PDF"


async def test_project_problem_is_error_build_without_log(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    await write(user_client, lab, "out/old.tex", "старый результат")

    build = await built(user_client, build_worker, lab)

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


async def test_latest_build_is_last_requested(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    await built(user_client, build_worker, lab)
    await write(user_client, lab, "sections/intro.tex", "Правка")
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 700}
    failed = await built(user_client, build_worker, lab)
    # Ещё не собранная сборка — тоже последняя: студент видит, что она в очереди.
    queued = await start(user_client, lab)

    response = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")

    assert failed["status"] == "error"
    assert response.json() == queued


async def test_latest_successful_build_survives_failed_one(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    ok = await built(user_client, build_worker, lab)
    await write(user_client, lab, "sections/intro.tex", "Правка")
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 700}
    await built(user_client, build_worker, lab)
    await start(user_client, lab)

    response = await user_client.get(f"/api/v1/projects/{lab}/builds/latest?status=ok")

    # После неудачной сборки и пока идёт следующая студент видит прошлый удачный PDF.
    assert response.status_code == 200, response.text
    assert response.json() == ok
    pdf = await user_client.get(f"/api/v1/builds/{ok['id']}/pdf")
    assert pdf.content == PDF


async def test_latest_successful_build_is_404_until_one_succeeds(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 700}
    await built(user_client, build_worker, lab)

    response = await user_client.get(f"/api/v1/projects/{lab}/builds/latest?status=ok")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Удачных сборок ещё не было",
        "details": {},
    }


async def test_latest_build_filters_only_by_ok(
    user_client: AsyncClient, fake: FakeCompiler, lab: str
) -> None:
    response = await user_client.get(f"/api/v1/projects/{lab}/builds/latest?status=error")

    assert response.status_code == 422


async def test_rebuild_without_changes_comes_from_cache(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    first = await built(user_client, build_worker, lab)
    second = await built(user_client, build_worker, lab)

    assert len(fake.requests) == 1
    assert second["id"] != first["id"]
    assert (second["status"], second["has_pdf"]) == ("ok", True)
    latest = await user_client.get(f"/api/v1/projects/{lab}/builds/latest")
    assert latest.json()["id"] == second["id"]
    pdf = await user_client.get(f"/api/v1/builds/{second['id']}/pdf")
    assert pdf.content == PDF


async def test_pdf_gone_from_storage_is_404(
    app: FastAPI, user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    build = await built(user_client, build_worker, lab)
    storage: LocalStorage = app.state.storage
    for path in storage.root.rglob("*"):
        if path.is_file():
            path.unlink()

    response = await user_client.get(f"/api/v1/builds/{build['id']}/pdf")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Файл сборки не найден. Соберите проект ещё раз."


async def test_compiler_unavailable_is_error_build_with_message(
    user_client: AsyncClient, build_worker: BuildWorker, fake: FakeCompiler, lab: str
) -> None:
    fake.error = httpx.ConnectError("refused")

    build = await built(user_client, build_worker, lab)

    # Не HTTP-ошибка, а итог сборки — там же, где ошибки LaTeX.
    assert (build["status"], build["has_pdf"]) == ("error", False)
    assert [error["message"] for error in build["errors"]] == [
        "Сервис сборки сейчас недоступен. Попробуйте через минуту."
    ]


async def test_someone_elses_builds_are_not_found(
    user_client: AsyncClient,
    sign_up: SignUp,
    build_worker: BuildWorker,
    fake: FakeCompiler,
    lab: str,
) -> None:
    build = await built(user_client, build_worker, lab)
    await sign_up("petrov@example.com")
    user_client.headers.update(CSRF)

    urls = [
        ("POST", f"/api/v1/projects/{lab}/builds"),
        ("GET", f"/api/v1/projects/{lab}/builds/latest"),
        ("GET", f"/api/v1/projects/{lab}/builds/latest?status=ok"),
        ("GET", f"/api/v1/builds/{build['id']}"),
        ("GET", f"/api/v1/builds/{build['id']}/pdf"),
        ("GET", f"/api/v1/builds/{build['id']}/log"),
    ]
    for method, url in urls:
        response = await user_client.request(method, url)
        assert response.status_code == 404, url
    assert len(fake.requests) == 1
    assert build_worker.queued == []


async def test_unknown_build_is_not_found(user_client: AsyncClient, fake: FakeCompiler) -> None:
    response = await user_client.get("/api/v1/builds/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Сборка не найдена"


async def test_builds_need_sign_in(db_client: AsyncClient, fake: FakeCompiler, lab: str) -> None:
    db_client.cookies.clear()

    response = await db_client.get(f"/api/v1/projects/{lab}/builds/latest")

    assert response.status_code == 401
