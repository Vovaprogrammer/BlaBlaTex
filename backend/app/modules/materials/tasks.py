"""Извлечение текста материалов в воркере (architecture.md 5): задача, постановка в очередь
и фоновая проверка материалов, чьё задание потерялось."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.broker import WorkerEvents, WorkerSessions, WorkerStorage, broker
from app.core.errors import AppError
from app.core.events import EventPublisher, EventType, MaterialReadyData
from app.core.storage import Storage
from app.modules.materials import extraction
from app.modules.materials import service as materials_service
from app.modules.materials.extraction import Extracted, ExtractionFailed
from app.modules.materials.service import Outcome
from app.modules.projects import service as projects_service
from app.modules.projects.models import File

logger = structlog.get_logger(__name__)

# Сколько запись файлов ждёт очередь — на все материалы сразу. Не дождалась — материалы
# отправит фоновая проверка, а запись уже сохранена.
ENQUEUE_TIMEOUT_S = 2
# Как часто воркер ищет материалы, чьё задание потерялось.
SWEEP_INTERVAL_S = 30

FAILED_MESSAGE = "Не удалось обработать файл из-за сбоя сервиса. Загрузите его ещё раз."

Extract = Callable[[str | None, str | bytes], Awaitable[Extracted]]
# Как разбудить воркер для материалов: в API и воркере — задача ниже, в тестах — подмена.
Enqueue = Callable[[Sequence[uuid.UUID]], Awaitable[None]]


@broker.task(task_name="materials.extract")
async def extract_material_job(
    file_id: uuid.UUID,
    sessionmaker: WorkerSessions,
    storage: WorkerStorage,
    events: WorkerEvents,
) -> None:
    """Извлечение текста одного материала. Задание может прийти повторно — тогда текст уже
    извлечён, и задача ничего не делает."""
    await extract_material(file_id, sessionmaker=sessionmaker, storage=storage, events=events)


async def enqueue_extraction(file_ids: Sequence[uuid.UUID]) -> None:
    """Будит воркер для материалов после commit записи.

    Ошибку не бросает: запись уже сохранена, и студент не должен получить ошибку из-за
    очереди. Не вышло — в лог; материалы через пару минут отправит фоновая проверка.
    """
    try:
        async with asyncio.timeout(ENQUEUE_TIMEOUT_S):
            for file_id in file_ids:
                await extract_material_job.kiq(file_id)
    # Exception: любой сбой очереди (Redis, сеть, срок) — не повод отвечать студенту 500.
    except Exception as error:
        logger.warning(
            "material_queue_unavailable",
            count=len(file_ids),
            reason=repr(error.__cause__ or error),
        )


async def extract_material(
    file_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    events: EventPublisher,
    extract: Extract = extraction.extract,
) -> None:
    """Извлекает текст материала и записывает итог, если файл с тех пор не менялся.

    Сначала материал берётся в работу (claim) и в той же транзакции читается файл: так
    прочитанное содержимое — не старше метки, с которой сверяется запись итога. Извлечение —
    без соединения с базой. Пока оно шло, файл могли заменить, удалить или перенести из
    materials/ — тогда итог не записывается и события нет: новую версию обработает своё
    задание. После записи — material.ready с путём файла на этот момент.
    """
    async with sessionmaker() as session:
        token = await materials_service.claim(session, file_id)
        file = await projects_service.get_file(session, file_id) if token else None
        await session.commit()
    if token is None or file is None:
        return
    outcome = await _outcome(file, storage, extract)
    async with sessionmaker() as session:
        saved = await materials_service.save_result(session, file_id, token, outcome)
        path = await projects_service.get_path(session, file_id) if saved else None
        await session.commit()
    if path is None:
        logger.info("material_result_discarded", file_id=str(file_id))
        return
    logger.info("material_extracted", file_id=str(file_id), status=outcome.status)
    await events.publish(
        file.project_id,
        EventType.MATERIAL_READY,
        MaterialReadyData(path=path, status=outcome.status),
    )


async def _outcome(file: File, storage: Storage, extract: Extract) -> Outcome:
    """Итог извлечения. Ошибка — понятное сообщение студенту, подробности — в лог."""
    try:
        if file.kind == "text":
            content: str | bytes = file.content or ""
        else:
            stream = await projects_service.open_binary(storage, file)
            content = b"".join([chunk async for chunk in stream])
        extracted = await extract(file.mime, content)
    except ExtractionFailed as failed:
        logger.warning("material_extraction_failed", file_id=str(file.id), **failed.detail)
        return Outcome(status="failed", error=failed.message)
    except AppError as error:
        # Blob потерян (open_binary уже записал в лог): помогает только загрузить заново.
        return Outcome(status="failed", error=error.message)
    # Exception: сбой в нашем коде не должен оставить материал pending навсегда — фоновая
    # проверка отправляла бы его снова и снова.
    except Exception:
        logger.exception("material_extraction_crashed", file_id=str(file.id))
        return Outcome(status="failed", error=FAILED_MESSAGE)
    return Outcome(
        status="ready", text=extracted.text, method=extracted.method, pages=extracted.pages
    )


async def sweep_materials(
    sessionmaker: async_sessionmaker[AsyncSession], enqueue: Enqueue = enqueue_extraction
) -> None:
    """Снова отправляет воркеру материалы, которые ждут извлечения дольше пары минут."""
    async with sessionmaker() as session:
        stale = await materials_service.requeue_stale(session)
        await session.commit()
    if stale:
        logger.info("materials_requeued", count=len(stale))
        await enqueue(stale)


async def watch_materials(
    sessionmaker: async_sessionmaker[AsyncSession], interval_s: float = SWEEP_INTERVAL_S
) -> None:
    """Проверяет материалы сразу и потом каждые interval_s секунд, пока работает воркер.

    Так обработаются материалы, загруженные, пока очередь была недоступна или воркер
    лежал, и загруженные до B2.7. Сбой одной проверки не останавливает следующие.
    """
    while True:
        try:
            await sweep_materials(sessionmaker)
        except Exception:
            logger.exception("material_sweep_failed")
        await asyncio.sleep(interval_s)
