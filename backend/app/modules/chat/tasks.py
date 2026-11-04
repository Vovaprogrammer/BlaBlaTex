"""Прогоны агента в воркере (architecture.md 8): задача прогона и постановка в очередь."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq.exceptions import SendTaskError

from app.core.broker import broker
from app.core.errors import AppError, ErrorCode
from app.modules.chat import service
from app.modules.projects.models import Project

logger = structlog.get_logger(__name__)

# Сколько POST /messages ждёт очередь: без срока при недоступном Redis запрос висел бы
# десятки секунд.
ENQUEUE_TIMEOUT_S = 5
QUEUE_UNAVAILABLE_MESSAGE = "ИИ сейчас недоступен. Попробуйте через минуту."

# Как разбудить воркер для прогона: в API и воркере — задача ниже, в тестах — подмена.
Enqueue = Callable[[uuid.UUID], Awaitable[None]]


@broker.task(task_name="chat.run")
async def run_agent_job(run_id: uuid.UUID) -> None:
    """Прогон агента из очереди. Задание может прийти повторно."""
    logger.info("agent_run_received", run_id=str(run_id))


async def enqueue_run(run_id: uuid.UUID) -> None:
    """Отправляет прогон воркеру. Очередь недоступна — SendTaskError."""
    await run_agent_job.kiq(run_id)


async def post_message(
    session: AsyncSession,
    project: Project,
    user_id: uuid.UUID,
    text: str,
    enqueue: Enqueue = enqueue_run,
) -> service.NewRun:
    """Сообщение студента и прогон в очереди; будит воркер.

    Очередь недоступна — 500, а сообщение, прогон и пустой changeset удаляются: без
    воркера прогон так и ждал бы в очереди, и проект нельзя было бы снова спросить.
    """
    created = await service.create_message(session, project, user_id, text)
    try:
        async with asyncio.timeout(ENQUEUE_TIMEOUT_S):
            await enqueue(created.run.id)
    except (SendTaskError, TimeoutError) as error:
        logger.warning(
            "agent_queue_unavailable",
            run_id=str(created.run.id),
            reason=repr(error.__cause__ or error),
        )
        await service.discard_run(session, created.run.id)
        raise AppError(ErrorCode.INTERNAL, QUEUE_UNAVAILABLE_MESSAGE, 500) from error
    return created
