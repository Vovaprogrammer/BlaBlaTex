"""Как воркер ведёт прогон, пока работает агент (architecture.md 8): отмена, потеря
блокировки, остановка и падение воркера, повторное задание, фоновая проверка.

Тесты — на настоящих соединениях (фикстура live): прогон и агент ходят в базу параллельно.
"""

import asyncio
import time
import uuid
from contextlib import suppress
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.errors import AppError
from app.core.events import EventType
from app.modules.agent.contract import RunRequest, RunResult
from app.modules.chat import runner, tasks
from app.modules.chat import service as chat_service
from app.modules.chat.models import AgentRun
from app.modules.projects import history
from app.modules.projects import service as projects_service
from app.modules.projects.history import Writer
from app.modules.projects.models import Project
from app.modules.templates.registry import Registry, load_templates
from tests.fake_events import FakeEvents
from tests.helpers import TEMPLATE_FIXTURES, writer
from tests.live_builds import Live
from tests.live_runs import (
    USAGE,
    execute,
    expire_lock,
    lock_holder,
    new_run,
    parts,
    reply_of,
    request_cancel,
    stored_run,
    wait_status,
)


@pytest.fixture
def templates() -> Registry:
    return load_templates(TEMPLATE_FIXTURES)


async def never_called(request: RunRequest) -> RunResult:
    raise AssertionError("Агент не должен запускаться второй раз")


async def test_cancel_stops_listening_agent(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    events = FakeEvents()

    async def agent(request: RunRequest) -> RunResult:
        await request.events.delta("Начал")
        await request.cancel.wait()
        return RunResult(status="cancelled", text="Начал", usage=USAGE)

    job = asyncio.create_task(execute(live, run_id, events, templates, agent))
    await wait_status(live, run_id, "running")
    await request_cancel(live, run_id)
    async with asyncio.timeout(5):
        await job

    run = await stored_run(live, run_id)
    assert (run.status, run.error, run.tokens_in) == ("cancelled", None, 120)
    reply = await reply_of(live, project_id)
    assert reply.status == "cancelled"
    # Пришедший текст сохраняется; правки до отмены остались бы в changeset прогона.
    assert parts(reply) == [{"type": "text", "text": "Начал"}]
    assert events.types[-2:] == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]
    assert events.published[-2].data.model_dump()["status"] == "cancelled"
    assert await lock_holder(live, project_id) is None


async def test_cancel_stops_stuck_agent_within_five_seconds(
    live: Live, templates: Registry
) -> None:
    project_id, run_id = await new_run(live)

    async def agent(request: RunRequest) -> RunResult:
        await request.events.delta("Пишу")
        # Агент не смотрит на cancel: воркер прерывает его сам.
        await asyncio.sleep(60)
        return RunResult(status="done", text="", usage=USAGE)

    # Настоящие сроки воркера: отмена должна уложиться в 5 с.
    job = asyncio.create_task(
        execute(live, run_id, FakeEvents(), templates, agent, runner.DEFAULT_TIMING)
    )
    await wait_status(live, run_id, "running")
    began = time.monotonic()
    await request_cancel(live, run_id)
    async with asyncio.timeout(10):
        await job

    assert time.monotonic() - began < 5
    run = await stored_run(live, run_id)
    assert (run.status, run.model) == ("cancelled", None)
    assert parts(await reply_of(live, project_id)) == [{"type": "text", "text": "Пишу"}]
    assert await lock_holder(live, project_id) is None


async def test_lost_lock_stops_run(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    events = FakeEvents()

    async def agent(request: RunRequest) -> RunResult:
        await request.cancel.wait()
        return RunResult(status="cancelled", text="", usage=USAGE)

    job = asyncio.create_task(execute(live, run_id, events, templates, agent))
    await wait_status(live, run_id, "running")
    # Воркер не продлил блокировку вовремя (например, база отвечала слишком долго):
    # студент уже мог править проект, и прогон останавливается.
    await expire_lock(live, project_id)
    async with asyncio.timeout(5):
        await job

    run = await stored_run(live, run_id)
    assert (run.status, run.error) == ("failed", chat_service.RUN_INTERRUPTED_MESSAGE)
    assert parts(await reply_of(live, project_id)) == [
        {"type": "error", "text": chat_service.RUN_INTERRUPTED_MESSAGE}
    ]
    assert events.types[-2:] == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]


async def test_lock_is_renewed_during_long_run(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    release = asyncio.Event()

    async def agent(request: RunRequest) -> RunResult:
        await release.wait()
        return RunResult(status="done", text="Готово", usage=USAGE)

    job = asyncio.create_task(execute(live, run_id, FakeEvents(), templates, agent))
    await wait_status(live, run_id, "running")
    async with live.sessionmaker() as session:
        first = await session.get(Project, project_id)
        assert first is not None
        until = first.run_lock_until
    await asyncio.sleep(0.2)
    async with live.sessionmaker() as session:
        later = await session.get(Project, project_id)
        assert later is not None
        renewed_until = later.run_lock_until
    release.set()
    await job

    assert until is not None and renewed_until is not None
    assert renewed_until > until
    assert (await stored_run(live, run_id)).status == "done"


async def test_redelivered_job_while_running_does_nothing(live: Live, templates: Registry) -> None:
    _, run_id = await new_run(live)
    release = asyncio.Event()

    async def agent(request: RunRequest) -> RunResult:
        await release.wait()
        return RunResult(status="done", text="Готово", usage=USAGE)

    job = asyncio.create_task(execute(live, run_id, FakeEvents(), templates, agent))
    await wait_status(live, run_id, "running")
    second = FakeEvents()

    # Задание пришло ещё раз (прогон идёт дольше 10 минут): блокировка жива — не трогаем.
    await execute(live, run_id, second, templates, never_called)

    assert second.published == []
    assert (await stored_run(live, run_id)).status == "running"
    release.set()
    await job
    assert (await stored_run(live, run_id)).status == "done"


async def test_worker_stop_interrupts_run(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    events = FakeEvents()

    began = asyncio.Event()

    async def agent(request: RunRequest) -> RunResult:
        await request.events.delta("Начал")
        began.set()
        await asyncio.sleep(60)
        return RunResult(status="done", text="", usage=USAGE)

    job = asyncio.create_task(execute(live, run_id, events, templates, agent))
    # Агент начинает не сразу при running, а после проверки материалов проекта.
    async with asyncio.timeout(5):
        await began.wait()
    job.cancel()
    with suppress(asyncio.CancelledError):
        await job

    run = await stored_run(live, run_id)
    assert (run.status, run.error) == ("failed", chat_service.RUN_INTERRUPTED_MESSAGE)
    assert parts(await reply_of(live, project_id)) == [
        {"type": "text", "text": "Начал"},
        {"type": "error", "text": chat_service.RUN_INTERRUPTED_MESSAGE},
    ]
    assert events.types[-2:] == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]
    assert await lock_holder(live, project_id) is None


async def crash_after_start(live: Live, project_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """Воркер взял прогон и упал: проект занят, но блокировку никто не продлевает."""
    async with live.sessionmaker() as session:
        assert await history.take_run_lock(session, project_id, run_id)
        await session.execute(
            update(AgentRun).where(AgentRun.id == run_id).values(status="running")
        )
        await session.commit()


async def save(live: Live, project_id: uuid.UUID, path: str) -> None:
    async with live.sessionmaker() as session:
        await projects_service.write_text_file(session, writer(), project_id, path, "текст")


async def test_crashed_worker_lock_expires_and_run_is_closed(
    live: Live, templates: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(history, "RUN_LOCK_TTL", timedelta(milliseconds=300))
    swept_project, swept_run = await new_run(live)
    redelivered_project, redelivered_run = await new_run(live)
    await crash_after_start(live, swept_project, swept_run)
    await crash_after_start(live, redelivered_project, redelivered_run)

    # Пока срок не истёк, студент проект не правит.
    with pytest.raises(AppError) as locked:
        await save(live, swept_project, "early.tex")
    assert locked.value.status == 423
    await asyncio.sleep(0.4)
    # Срок истёк — студент снова правит, даже если воркер так и не поднялся.
    await save(live, swept_project, "late.tex")

    # Задание упавшего воркера пришло снова: агент не запускается, прогон закрыт.
    redelivered_events = FakeEvents()
    await execute(live, redelivered_run, redelivered_events, templates, never_called)
    # Остальное закрывает фоновая проверка поднявшегося воркера.
    swept_events = FakeEvents()
    requeued: list[uuid.UUID] = []

    async def enqueue(run_id: uuid.UUID) -> None:
        requeued.append(run_id)

    await tasks.sweep_runs(live.sessionmaker, swept_events, enqueue)

    for run_id, events in ((redelivered_run, redelivered_events), (swept_run, swept_events)):
        run = await stored_run(live, run_id)
        assert (run.status, run.error) == ("failed", chat_service.RUN_INTERRUPTED_MESSAGE)
        mine = [e for e in events.published if e.data.model_dump()["run_id"] == run_id]
        assert [e.type for e in mine] == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]
    assert requeued == []
    for project_id in (swept_project, redelivered_project):
        assert await lock_holder(live, project_id) is None


async def test_sweep_requeues_lost_queued_run(live: Live) -> None:
    _, lost = await new_run(live)
    _, fresh = await new_run(live)
    async with live.sessionmaker() as session:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == lost)
            .values(created_at=AgentRun.created_at - chat_service.LOST_AFTER * 2)
        )
        await session.commit()
    requeued: list[uuid.UUID] = []

    async def enqueue(run_id: uuid.UUID) -> None:
        requeued.append(run_id)

    await tasks.sweep_runs(live.sessionmaker, FakeEvents(), enqueue)

    assert requeued == [lost]
    assert fresh not in requeued


async def test_interrupted_run_keeps_changes_card(live: Live) -> None:
    project_id, run_id = await new_run(live)
    await crash_after_start(live, project_id, run_id)
    changeset_id = (await stored_run(live, run_id)).changeset_id
    assert changeset_id is not None
    async with live.sessionmaker() as session:
        ai = Writer(FakeEvents(), "ai", live.owner_id, changeset_id)
        await projects_service.write_text_file(session, ai, project_id, "ai.tex", "ИИ\n")
    await expire_lock(live, project_id)

    await tasks.sweep_runs(live.sessionmaker, FakeEvents(), never_enqueued)

    # Воркер упал после правок: что успел записать ИИ, студент видит в чате и может откатить.
    assert parts(await reply_of(live, project_id)) == [
        {"type": "changeset", "changeset_id": str(changeset_id)},
        {"type": "error", "text": chat_service.RUN_INTERRUPTED_MESSAGE},
    ]


async def test_late_parts_do_not_overwrite_closed_run(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    swept = asyncio.Event()

    async def agent(request: RunRequest) -> RunResult:
        await swept.wait()
        await request.events.delta("Поздно")
        # Воркер успевает сохранить части, прежде чем агент вернётся.
        await asyncio.sleep(0.1)
        return RunResult(status="cancelled", text="", usage=USAGE)

    # Долгий срок на отмену: агент не прерывается раньше, чем пришлёт поздний текст.
    timing = runner.RunTiming(tick_s=0.01, renew_s=0.05, cancel_grace_s=2.0)
    job = asyncio.create_task(execute(live, run_id, FakeEvents(), templates, agent, timing))
    await wait_status(live, run_id, "running")
    # Воркер жив, но не продлил блокировку вовремя, и прогон закрыла фоновая проверка.
    await expire_lock(live, project_id)
    await tasks.sweep_runs(live.sessionmaker, FakeEvents(), never_enqueued)
    swept.set()
    async with asyncio.timeout(5):
        await job

    run = await stored_run(live, run_id)
    assert (run.status, run.error) == ("failed", chat_service.RUN_INTERRUPTED_MESSAGE)
    assert parts(await reply_of(live, project_id)) == [
        {"type": "error", "text": chat_service.RUN_INTERRUPTED_MESSAGE}
    ]


async def test_cancel_of_dead_run_closes_it_at_once(live: Live) -> None:
    project_id, run_id = await new_run(live)
    await crash_after_start(live, project_id, run_id)
    await expire_lock(live, project_id)
    events = FakeEvents()

    # Воркер упал, отметку отмены некому увидеть: прогон закрывается сразу, без проверки.
    async with live.sessionmaker() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        await chat_service.stop_run(session, events, run)
        assert (run.status, run.error) == ("failed", chat_service.RUN_INTERRUPTED_MESSAGE)

    assert events.types == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]
    assert await lock_holder(live, project_id) is None


async def never_enqueued(run_id: uuid.UUID) -> None:
    raise AssertionError(f"прогон {run_id} не должен уходить в очередь")
