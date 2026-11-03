"""Очередь сборок без гонок: постановка, начало, итог, зависшие и потерянные сборки.

Компилятор подменён (tests/fake_compiler.py), Storage — во временной папке. Гонки
нескольких воркеров — в test_build_races.py, на настоящих отдельных соединениях.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import INTERNAL_MESSAGE, AppError
from app.core.storage import LocalStorage
from app.modules.auth import service as auth_service
from app.modules.builds.models import Build
from app.modules.builds.service import (
    COMPILER_UNAVAILABLE_MESSAGE,
    STALE_MESSAGE,
    lost_queued_builds,
    mark_stale_builds,
    queue_build,
    run_queued_build,
    start_build,
)
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from tests.fake_compiler import FakeCompiler
from tests.helpers import create_empty_project

MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nПривет\n\\end{document}\n"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def fake() -> FakeCompiler:
    return FakeCompiler()


@pytest.fixture
async def lab(db_session: AsyncSession) -> Project:
    """Проект с одним main.tex."""
    user, _ = await auth_service.register(db_session, "ivanov@example.com", "password1")
    project = await create_empty_project(db_session, user.id)
    await projects_service.write_text_file(db_session, project.id, "main.tex", MAIN_TEX)
    return project


async def run(
    session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, build: Build
) -> Build | None:
    return await run_queued_build(session, storage, fake.client(), build.id)


async def statuses(session: AsyncSession, project: Project) -> list[str]:
    result = await session.scalars(
        select(Build.status).where(Build.project_id == project.id).order_by(Build.created_at)
    )
    return list(result)


async def backdate(session: AsyncSession, build: Build, column: str, minutes: int) -> None:
    moment = datetime.now(UTC) - timedelta(minutes=minutes)
    await session.execute(update(Build).where(Build.id == build.id).values({column: moment}))
    await session.commit()


# Постановка в очередь.


async def test_queued_build_waits_without_result(db_session: AsyncSession, lab: Project) -> None:
    build = await queue_build(db_session, lab)

    assert (build.status, build.engine, build.started_at) == ("queued", "xelatex", None)
    assert (build.inputs_hash, build.pdf_sha256, build.errors) == (None, None, [])


async def test_second_request_while_queued_returns_same_build(
    db_session: AsyncSession, lab: Project
) -> None:
    first = await queue_build(db_session, lab)

    second = await queue_build(db_session, lab)

    assert second.id == first.id
    assert await statuses(db_session, lab) == ["queued"]


async def test_request_while_running_queues_next_build(
    db_session: AsyncSession, lab: Project
) -> None:
    first = await queue_build(db_session, lab)
    await start_build(db_session, first.id)

    second = await queue_build(db_session, lab)

    assert second.id != first.id
    assert await statuses(db_session, lab) == ["running", "queued"]


async def test_queue_for_deleted_project_is_not_found(
    db_session: AsyncSession, lab: Project
) -> None:
    await db_session.delete(lab)
    await db_session.commit()

    with pytest.raises(AppError) as error:
        await queue_build(db_session, lab)

    assert (error.value.status, error.value.message) == (404, "Проект не найден")


# Начало и итог.


async def test_queued_build_runs_to_result(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    queued = await queue_build(db_session, lab)

    result = await run(db_session, storage, fake, queued)

    assert result is not None
    assert result.id == queued.id
    assert (result.status, result.pages, result.duration_ms) == ("ok", 1, 1500)
    assert result.started_at is not None
    assert result.inputs_hash and result.pdf_sha256 and result.log_sha256
    assert len(fake.requests) == 1


async def test_files_are_read_when_build_starts(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    queued = await queue_build(db_session, lab)
    # Студент поправил файл, пока сборка ждала очереди: правка попадает в неё.
    await projects_service.write_text_file(db_session, lab.id, "main.tex", MAIN_TEX + "%\n")

    await run(db_session, storage, fake, queued)

    assert fake.requests[0].files()["main.tex"] == (MAIN_TEX + "%\n").encode()


async def test_build_starts_only_once(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    queued = await queue_build(db_session, lab)
    await run(db_session, storage, fake, queued)

    # Задание пришло ещё раз — например, его отправила проверка потерянных сборок.
    again = await run(db_session, storage, fake, queued)

    assert again is None
    assert len(fake.requests) == 1


async def test_build_does_not_start_while_another_runs(
    db_session: AsyncSession, lab: Project
) -> None:
    first = await queue_build(db_session, lab)
    await start_build(db_session, first.id)
    second = await queue_build(db_session, lab)

    assert await start_build(db_session, second.id) is None
    assert await statuses(db_session, lab) == ["running", "queued"]


async def test_rebuild_without_changes_comes_from_cache(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    first = await run(db_session, storage, fake, await queue_build(db_session, lab))
    second = await run(db_session, storage, fake, await queue_build(db_session, lab))

    assert first is not None and second is not None
    assert len(fake.requests) == 1
    assert second.id != first.id
    assert (second.status, second.pdf_sha256) == ("ok", first.pdf_sha256)


async def test_project_problem_is_build_result(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    await projects_service.delete_path(db_session, lab.id, "main.tex")

    result = await run(db_session, storage, fake, await queue_build(db_session, lab))

    assert result is not None
    assert result.status == "error"
    assert result.errors[0]["message"] == (
        "В проекте нет главного файла main.tex. Создайте его или верните удалённый."
    )
    assert fake.requests == []


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("connect", COMPILER_UNAVAILABLE_MESSAGE),
        ("server-error", COMPILER_UNAVAILABLE_MESSAGE),
        ("rejected", INTERNAL_MESSAGE),
        ("broken", INTERNAL_MESSAGE),
    ],
)
async def test_compiler_failure_is_error_build_with_message(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    setup: str,
    message: str,
) -> None:
    responses = {
        "server-error": httpx.Response(500),
        "rejected": httpx.Response(422, json={"error": {"code": "validation_error"}}),
        "broken": httpx.Response(200, content=b"not a tar.gz"),
    }
    if setup == "connect":
        fake.error = httpx.ConnectError("refused")
    else:
        fake.respond = lambda request: responses[setup]

    result = await run(db_session, storage, fake, await queue_build(db_session, lab))

    # Не HTTP-ошибка, а итог сборки: его увидят и студент, и ИИ-агент.
    assert result is not None
    assert (result.status, result.log_sha256, result.pdf_sha256) == ("error", None, None)
    assert [error["message"] for error in result.errors] == [message]


async def test_unexpected_failure_does_not_leave_build_running(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise ValueError("ошибка в коде")

    fake.respond = respond

    result = await run(db_session, storage, fake, await queue_build(db_session, lab))

    assert result is not None
    assert result.status == "error"
    assert [error["message"] for error in result.errors] == [INTERNAL_MESSAGE]


async def test_database_failure_does_not_leave_build_running(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(session: AsyncSession, project_id: object) -> None:
        # Запрос падает посреди транзакции: без отката итог было бы не записать.
        await session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(projects_service, "list_build_files", broken)

    result = await run(db_session, storage, fake, await queue_build(db_session, lab))

    assert result is not None
    assert result.status == "error"
    assert [error["message"] for error in result.errors] == [INTERNAL_MESSAGE]


async def test_project_deleted_during_build(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        await db_session.delete(lab)
        await db_session.commit()
        return fake.build_response()

    fake.respond = respond

    result = await run(db_session, storage, fake, await queue_build(db_session, lab))

    assert result is None
    count = await db_session.scalar(select(func.count()).select_from(Build))
    assert count == 0


# Зависшие и потерянные сборки.


async def test_stale_running_build_becomes_timeout(db_session: AsyncSession, lab: Project) -> None:
    build = await queue_build(db_session, lab)
    await start_build(db_session, build.id)
    await backdate(db_session, build, "started_at", minutes=4)

    [stale] = await mark_stale_builds(db_session)

    assert (stale.id, stale.status) == (build.id, "timeout")
    assert [error["message"] for error in stale.errors] == [STALE_MESSAGE]


async def test_fresh_and_queued_builds_are_not_stale(
    db_session: AsyncSession, lab: Project
) -> None:
    running = await queue_build(db_session, lab)
    await start_build(db_session, running.id)
    queued = await queue_build(db_session, lab)
    # В очереди сборка может законно ждать окончания предыдущей: время в очереди не в счёт.
    await backdate(db_session, queued, "created_at", minutes=10)

    assert await mark_stale_builds(db_session) == []
    assert await statuses(db_session, lab) == ["queued", "running"]


async def test_result_of_stale_build_is_dropped(
    db_session: AsyncSession, storage: LocalStorage, fake: FakeCompiler, lab: Project
) -> None:
    build = await queue_build(db_session, lab)

    async def respond(request: httpx.Request) -> httpx.Response:
        # Воркер собирал слишком долго: проверка уже поставила сборке timeout.
        await backdate(db_session, build, "started_at", minutes=4)
        await mark_stale_builds(db_session)
        return fake.build_response()

    fake.respond = respond

    assert await run(db_session, storage, fake, build) is None
    stored = await db_session.get(Build, build.id, populate_existing=True)
    assert stored is not None
    assert (stored.status, stored.pdf_sha256) == ("timeout", None)


async def test_wait_for_compiler_slot_is_not_stale(
    db_session: AsyncSession,
    storage: LocalStorage,
    fake: FakeCompiler,
    lab: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = await queue_build(db_session, lab)
    list_build_files = projects_service.list_build_files

    async def slow_start(session: AsyncSession, project_id: uuid.UUID) -> list[File]:
        # Сборка началась давно и всё это время ждала места у компилятора.
        await backdate(session, build, "started_at", minutes=4)
        return await list_build_files(session, project_id)

    async def respond(request: httpx.Request) -> httpx.Response:
        stale.extend(await mark_stale_builds(db_session))
        return fake.build_response()

    stale: list[Build] = []
    monkeypatch.setattr(projects_service, "list_build_files", slow_start)
    fake.respond = respond

    result = await run(db_session, storage, fake, build)

    assert stale == []
    assert result is not None
    assert result.status == "ok"


async def test_lost_queued_builds(db_session: AsyncSession, lab: Project) -> None:
    other = await create_empty_project(db_session, lab.owner_id, "ЛР 2")
    busy = await create_empty_project(db_session, lab.owner_id, "ЛР 3")
    lost = await queue_build(db_session, lab)
    # Только что поставлена: её задание ещё может быть в пути к воркеру.
    await queue_build(db_session, other)
    running = await queue_build(db_session, busy)
    await start_build(db_session, running.id)
    waiting = await queue_build(db_session, busy)
    for build in (lost, waiting):
        await backdate(db_session, build, "created_at", minutes=2)

    # waiting ждёт идущую сборку своего проекта — её не трогаем.
    assert await lost_queued_builds(db_session) == [lost.id]
