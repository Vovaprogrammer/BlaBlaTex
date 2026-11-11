"""Прогоны агента на настоящих отдельных соединениях с базой: сообщение с прогоном,
выполнение прогона воркером и что из этого получилось.

Фикстура live — в conftest.py. Данные коммитятся по-настоящему; после теста пользователь
удаляется, а с ним и всё его (ON DELETE CASCADE).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update

from app.core.config import Settings
from app.modules.agent import stub
from app.modules.agent.contract import ModelUsage, RunRequest, RunResult
from app.modules.chat import runner
from app.modules.chat import service as chat_service
from app.modules.chat.models import AgentRun
from app.modules.chat.schemas import ChatMessageOut, RunStatus
from app.modules.llm.models import Usage
from app.modules.projects import history
from app.modules.projects.models import Project
from app.modules.templates.registry import Registry
from tests.fake_events import FakeEvents
from tests.live_builds import Live, new_project

Agent = Callable[[RunRequest], Awaitable[RunResult]]
USAGE = ModelUsage(model="test-model", tokens_in=120, tokens_out=45, cost=Decimal("0.0021"))
# Короткие сроки присмотра за агентом: тесты не ждут секунды.
FAST = runner.RunTiming(tick_s=0.01, renew_s=0.05, cancel_grace_s=0.2)


async def new_run(
    live: Live, text: str = "Сделай отчёт", project_id: uuid.UUID | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """Сообщение студента с прогоном в очереди → (проект, прогон)."""
    if project_id is None:
        project_id = await new_project(live)
    async with live.sessionmaker() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        created = await chat_service.create_message(
            session, project, live.owner_id, text, Settings(_env_file=None, app_env="test")
        )
        return project_id, created.run.id


async def execute(
    live: Live,
    run_id: uuid.UUID,
    events: FakeEvents,
    templates: Registry,
    agent: Agent = stub.run_agent,
    timing: runner.RunTiming = FAST,
    settings: Settings | None = None,
) -> None:
    """Прогон глазами воркера: с ресурсами live. Без settings — без LLM и своих ключей."""
    if settings is None:
        settings = Settings(_env_file=None, app_env="test", agent_run_max_tokens=10_000)
    await runner.execute_run(
        run_id,
        sessionmaker=live.sessionmaker,
        storage=live.storage,
        events=events,
        templates=templates,
        run_agent=agent,
        settings=settings,
        timing=timing,
    )


async def stored_run(live: Live, run_id: uuid.UUID) -> AgentRun:
    async with live.sessionmaker() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        return run


async def wait_status(live: Live, run_id: uuid.UUID, status: RunStatus) -> None:
    """Ждёт, пока прогон получит статус: воркер о нём не сообщает, остаётся спрашивать."""
    async with asyncio.timeout(5):
        while (await stored_run(live, run_id)).status != status:  # noqa: ASYNC110
            await asyncio.sleep(0.01)


async def reply_of(live: Live, project_id: uuid.UUID) -> ChatMessageOut:
    """Последнее сообщение чата — ответ ассистента."""
    async with live.sessionmaker() as session:
        items, _ = await chat_service.list_messages(session, project_id, before=None, limit=1)
    [reply] = items
    assert reply.role == "assistant"
    return reply


def parts(message: ChatMessageOut) -> list[dict[str, Any]]:
    return [part.model_dump(mode="json") for part in message.parts]


async def request_cancel(live: Live, run_id: uuid.UUID) -> None:
    """POST /runs/{rid}/cancel без HTTP."""
    async with live.sessionmaker() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        await chat_service.cancel_run(session, run)


async def expire_lock(live: Live, project_id: uuid.UUID) -> None:
    """Срок блокировки проекта истёк: её никто не продлил."""
    async with live.sessionmaker() as session:
        await session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(run_lock_until=func.clock_timestamp() - history.RUN_LOCK_TTL)
        )
        await session.commit()


async def lock_holder(live: Live, project_id: uuid.UUID) -> uuid.UUID | None:
    async with live.sessionmaker() as session:
        holders = await history.run_lock_holders(session, [project_id])
    return holders.get(project_id)


async def usage_of(live: Live) -> tuple[int, int, Decimal, int] | None:
    """Расход владельца за сегодня: (токены входа, выхода, стоимость, прогоны)."""
    async with live.sessionmaker() as session:
        row = await session.scalar(select(Usage).where(Usage.user_id == live.owner_id))
    if row is None:
        return None
    return row.tokens_in, row.tokens_out, row.cost, row.runs
