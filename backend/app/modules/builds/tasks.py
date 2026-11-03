"""Сборки в воркере (architecture.md 2, 9.1): задача сборки, постановка в очередь и
фоновая проверка зависших и потерянных сборок."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import TaskiqDepends, TaskiqState
from taskiq.exceptions import SendTaskError

from app.core.broker import WorkerSessions, WorkerStorage, broker, get_resource
from app.core.errors import AppError, ErrorCode
from app.modules.builds import service
from app.modules.builds.compiler import CompilerClient
from app.modules.builds.models import Build
from app.modules.projects.models import Project

logger = structlog.get_logger(__name__)

# Как часто воркер ищет зависшие и потерянные сборки (service.STALE_AFTER, LOST_AFTER).
SWEEP_INTERVAL_S = 30
# Сколько POST /builds ждёт очередь. Без срока при недоступном Redis запрос висел бы
# десятки секунд: клиент redis повторяет подключение с паузами.
ENQUEUE_TIMEOUT_S = 5

# Как разбудить воркер для сборки: в API и воркере — задача ниже, в тестах — подмена.
Enqueue = Callable[[uuid.UUID], Awaitable[None]]


def get_compiler(state: Annotated[TaskiqState, TaskiqDepends()]) -> CompilerClient:
    """Клиент компилятора воркера."""
    compiler: CompilerClient = get_resource(state, "compiler")
    return compiler


WorkerCompiler = Annotated[CompilerClient, TaskiqDepends(get_compiler)]


@broker.task(task_name="builds.run")
async def run_build(
    build_id: uuid.UUID,
    sessionmaker: WorkerSessions,
    storage: WorkerStorage,
    compiler: WorkerCompiler,
) -> None:
    """Собирает сборку из очереди, а за ней — ожидающие сборки её проекта.

    Задание может прийти повторно — тогда сборка уже начата, и задача ничего не делает.
    """
    await service.run_project_builds(sessionmaker, storage, compiler, build_id)


async def enqueue_build(build_id: uuid.UUID) -> None:
    """Отправляет сборку воркеру. Очередь недоступна — SendTaskError."""
    await run_build.kiq(build_id)


async def request_build(
    session: AsyncSession, project: Project, enqueue: Enqueue = enqueue_build
) -> Build:
    """Ставит сборку в очередь и будит воркер — для POST /builds и compile() у агента (B2.5).

    Пока сборка проекта ждёт в очереди, возвращается она же, и воркер второй раз не
    будится. Очередь недоступна — 500, а новая сборка удаляется: без воркера она так и
    ждала бы в очереди.
    """
    build, created = await service.queue_build(session, project)
    if created:
        try:
            async with asyncio.timeout(ENQUEUE_TIMEOUT_S):
                await enqueue(build.id)
        except (SendTaskError, TimeoutError) as error:
            logger.warning(
                "build_queue_unavailable",
                build_id=str(build.id),
                reason=repr(error.__cause__ or error),
            )
            await service.discard_queued_build(session, build.id)
            raise AppError(ErrorCode.INTERNAL, service.COMPILER_UNAVAILABLE_MESSAGE, 500) from error
    return build


async def sweep_builds(
    sessionmaker: async_sessionmaker[AsyncSession], enqueue: Enqueue = enqueue_build
) -> None:
    """Ставит timeout зависшим сборкам и снова отправляет воркеру потерянные."""
    async with sessionmaker() as session:
        await service.mark_stale_builds(session)
        lost = await service.lost_queued_builds(session)
    for build_id in lost:
        logger.info("build_requeued", build_id=str(build_id))
        await enqueue(build_id)


async def watch_builds(
    sessionmaker: async_sessionmaker[AsyncSession], interval_s: float = SWEEP_INTERVAL_S
) -> None:
    """Проверяет сборки сразу и потом каждые interval_s секунд, пока работает воркер.

    Так воркер, поднявшийся после падения, сам подбирает то, что осталось от прежнего.
    Сбой одной проверки (недоступны база или Redis) не останавливает следующие.
    """
    while True:
        try:
            await sweep_builds(sessionmaker)
        except Exception:
            logger.exception("build_sweep_failed")
        await asyncio.sleep(interval_s)
