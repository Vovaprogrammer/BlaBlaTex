"""Сборки в воркере: постановка в очередь, задача Taskiq и фоновая проверка сборок.

Redis не нужен: вместо очереди — подмена «разбудить воркер», а задачу через Taskiq
выполняет InMemoryBroker. База — настоящие отдельные соединения (фикстура live).
"""

import asyncio
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from taskiq import InMemoryBroker
from taskiq.exceptions import SendTaskError

from app.core.errors import AppError
from app.modules.builds import tasks
from app.modules.builds.models import Build
from app.modules.builds.service import COMPILER_UNAVAILABLE_MESSAGE, STALE_MESSAGE, start_build
from app.modules.projects import service as projects_service
from tests.fake_compiler import FakeCompiler
from tests.live_builds import MAIN_TEX, Live, builds_of, new_project, queue


class Sent(list[uuid.UUID]):
    """Подмена «разбудить воркер»: запоминает, какие сборки ему отправили."""

    async def __call__(self, build_id: uuid.UUID) -> None:
        self.append(build_id)


async def request(live: Live, project_id: uuid.UUID, enqueue: tasks.Enqueue) -> Build:
    async with live.sessionmaker() as session:
        project = await projects_service.get_project(session, project_id)
        assert project is not None
        return await tasks.request_build(session, project, enqueue)


async def backdate(live: Live, builds: list[Build], column: str, minutes: int) -> None:
    moment = datetime.now(UTC) - timedelta(minutes=minutes)
    async with live.sessionmaker() as session:
        await session.execute(
            update(Build)
            .where(Build.id.in_([build.id for build in builds]))
            .values({column: moment})
        )
        await session.commit()


# Постановка в очередь (POST /builds, позже compile() у агента).


async def test_worker_is_woken_only_for_new_build(live: Live) -> None:
    project_id = await new_project(live)
    sent = Sent()

    first = await request(live, project_id, sent)
    second = await request(live, project_id, sent)

    assert second.id == first.id
    assert sent == [first.id]


async def test_unavailable_queue_is_500_and_leaves_no_build(live: Live) -> None:
    project_id = await new_project(live)

    async def unavailable(build_id: uuid.UUID) -> None:
        raise SendTaskError

    with pytest.raises(AppError) as error:
        await request(live, project_id, unavailable)

    assert (error.value.status, error.value.message) == (500, COMPILER_UNAVAILABLE_MESSAGE)
    # Иначе сборка ждала бы в очереди, а воркер о ней не знал бы.
    assert await builds_of(live, project_id) == []


async def test_hanging_queue_is_500_without_waiting_long(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = await new_project(live)
    monkeypatch.setattr(tasks, "ENQUEUE_TIMEOUT_S", 0.05)

    async def hanging(build_id: uuid.UUID) -> None:
        # Redis не отвечает: клиент redis повторяет подключение с паузами.
        await asyncio.sleep(60)

    with pytest.raises(AppError) as error:
        await asyncio.wait_for(request(live, project_id, hanging), timeout=5)

    assert (error.value.status, error.value.message) == (500, COMPILER_UNAVAILABLE_MESSAGE)
    assert await builds_of(live, project_id) == []


# Задача воркера.


async def test_build_task_runs_through_taskiq(live: Live) -> None:
    # Задача получает id из сообщения очереди, а базу, хранилище и компилятор — из
    # ресурсов воркера, как в app/worker.py.
    memory = InMemoryBroker(await_inplace=True)
    memory.local_task_registry[tasks.run_build.task_name] = tasks.run_build
    fake = FakeCompiler()
    memory.state.sessionmaker = live.sessionmaker
    memory.state.storage = live.storage
    memory.state.compiler = fake.client()
    build = await queue(live, await new_project(live))
    try:
        await tasks.run_build.kicker().with_broker(memory).kiq(build.id)
    finally:
        await memory.shutdown()

    [stored] = await builds_of(live, build.project_id)
    assert (stored.id, stored.status) == (build.id, "ok")
    assert len(fake.requests) == 1


# Фоновая проверка сборок.


async def test_sweep_stops_stale_and_resends_lost_builds(live: Live) -> None:
    crashed_project = await new_project(live)
    stale = await queue(live, crashed_project)
    async with live.sessionmaker() as session:
        await start_build(session, stale.id)
    # Ждёт упавшую сборку своего проекта: воркер, который вёл её, передал бы очередь дальше.
    behind = await queue(live, crashed_project)
    lost = await queue(live, await new_project(live, MAIN_TEX + "%\n"))
    await backdate(live, [stale], "started_at", minutes=4)
    await backdate(live, [behind, lost], "created_at", minutes=2)
    sent = Sent()

    await tasks.sweep_builds(live.sessionmaker, sent)

    by_id = {build.id: build for build in await builds_of(live, crashed_project)}
    timed_out, waiting = by_id[stale.id], by_id[behind.id]
    assert timed_out.status == "timeout"
    assert [error["message"] for error in timed_out.errors] == [STALE_MESSAGE]
    assert waiting.status == "queued"
    assert sorted(sent) == sorted([behind.id, lost.id])


async def test_watch_continues_after_failed_check(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = 0
    recovered = asyncio.Event()

    async def flaky(*args: object) -> None:
        nonlocal checks
        checks += 1
        if checks == 1:
            raise RuntimeError("база недоступна")
        recovered.set()

    monkeypatch.setattr(tasks, "sweep_builds", flaky)
    watcher = asyncio.create_task(tasks.watch_builds(None, interval_s=0))  # type: ignore[arg-type]
    try:
        await asyncio.wait_for(recovered.wait(), timeout=5)
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher

    assert checks >= 2
