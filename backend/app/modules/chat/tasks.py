"""Прогоны агента в воркере (architecture.md 8): задача прогона, постановка в очередь
и фоновая проверка прерванных и потерянных прогонов."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import TaskiqDepends, TaskiqState
from taskiq.exceptions import SendTaskError

from app.core.broker import (
    WorkerEvents,
    WorkerSessions,
    WorkerStorage,
    broker,
    get_resource,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.events import EventPublisher
from app.modules.agent.contract import RunAgent
from app.modules.agent.runner import run_agent
from app.modules.chat import runner, service
from app.modules.projects.models import Project
from app.modules.templates.registry import Registry

logger = structlog.get_logger(__name__)

# Сколько POST /messages ждёт очередь: без срока при недоступном Redis запрос висел бы
# десятки секунд.
ENQUEUE_TIMEOUT_S = 5
QUEUE_UNAVAILABLE_MESSAGE = "ИИ сейчас недоступен. Попробуйте через минуту."
# Как часто воркер ищет прерванные и потерянные прогоны.
SWEEP_INTERVAL_S = 30

# Как разбудить воркер для прогона: в API и воркере — задача ниже, в тестах — подмена.
Enqueue = Callable[[uuid.UUID], Awaitable[None]]
# Точка подмены агента для тестов воркера.
AGENT: RunAgent = run_agent


def get_templates(state: Annotated[TaskiqState, TaskiqDepends()]) -> Registry:
    """Реестр шаблонов воркера: по нему инструменты агента отдают руководство шаблона."""
    templates: Registry = get_resource(state, "templates")
    return templates


WorkerTemplates = Annotated[Registry, TaskiqDepends(get_templates)]


@broker.task(task_name="chat.run")
async def run_agent_job(
    run_id: uuid.UUID,
    sessionmaker: WorkerSessions,
    storage: WorkerStorage,
    events: WorkerEvents,
    templates: WorkerTemplates,
) -> None:
    """Прогон агента из очереди. Задание может прийти повторно — тогда прогон уже не
    в очереди, и задача ничего не делает."""
    await runner.execute_run(
        run_id,
        sessionmaker=sessionmaker,
        storage=storage,
        events=events,
        templates=templates,
        run_agent=AGENT,
        settings=get_settings(),
    )


async def enqueue_run(run_id: uuid.UUID) -> None:
    """Отправляет прогон воркеру. Очередь недоступна — SendTaskError."""
    await run_agent_job.kiq(run_id)


async def post_message(
    session: AsyncSession,
    events: EventPublisher,
    project: Project,
    user_id: uuid.UUID,
    text: str,
    settings: Settings,
    enqueue: Enqueue = enqueue_run,
) -> service.NewRun:
    """Сообщение студента и прогон в очереди; будит воркер.

    Прогон проекта, прерванный падением воркера, сначала закрывается: студент не ждёт
    фоновую проверку. Очередь недоступна — 500, а сообщение, прогон и пустой changeset
    удаляются: без воркера прогон так и ждал бы в очереди, и проект нельзя было бы
    снова спросить. Очередь ответила поздно, а воркер уже взял прогон, — сообщение принято.
    """
    project_id = project.id
    closed = await service.close_dead_runs(session, project_id=project_id)
    await service.publish_closed(events, closed)
    created = await service.create_message(session, project, user_id, text, settings)
    try:
        async with asyncio.timeout(ENQUEUE_TIMEOUT_S):
            await enqueue(created.run.id)
    except (SendTaskError, TimeoutError) as error:
        reason = repr(error.__cause__ or error)
        if not await service.discard_run(session, created.run.id):
            # Очередь ответила поздно, но задание дошло: воркер уже взял прогон.
            logger.info("agent_queue_slow", run_id=str(created.run.id), reason=reason)
            return created
        logger.warning("agent_queue_unavailable", run_id=str(created.run.id), reason=reason)
        raise AppError(ErrorCode.INTERNAL, QUEUE_UNAVAILABLE_MESSAGE, 500) from error
    return created


async def sweep_runs(
    sessionmaker: async_sessionmaker[AsyncSession],
    events: EventPublisher,
    enqueue: Enqueue = enqueue_run,
) -> None:
    """Закрывает прогоны, чей воркер упал, и снова отправляет воркеру потерянные."""
    async with sessionmaker() as session:
        closed = await service.close_dead_runs(session)
        lost = await service.lost_queued_runs(session)
    for run in closed:
        logger.info("agent_run_closed_as_interrupted", run_id=str(run.run_id))
    await service.publish_closed(events, closed)
    for run_id in lost:
        logger.info("agent_run_requeued", run_id=str(run_id))
        await enqueue(run_id)


async def watch_runs(
    sessionmaker: async_sessionmaker[AsyncSession],
    events: EventPublisher,
    interval_s: float = SWEEP_INTERVAL_S,
) -> None:
    """Проверяет прогоны сразу и потом каждые interval_s секунд, пока работает воркер.

    Так воркер, поднявшийся после падения, сам закрывает прогоны прежнего. Сбой одной
    проверки (недоступны база или Redis) не останавливает следующие.
    """
    while True:
        try:
            await sweep_runs(sessionmaker, events)
        except Exception:
            logger.exception("agent_run_sweep_failed")
        await asyncio.sleep(interval_s)
