"""Извлечение текста материалов в воркере (architecture.md 5): задача, постановка в очередь
и фоновая проверка материалов, чьё задание потерялось."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.broker import WorkerEvents, WorkerSessions, WorkerStorage, broker
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.events import EventPublisher, EventType, MaterialReadyData
from app.core.storage import Storage
from app.modules.agent.contract import DescribeImage
from app.modules.llm import service as llm_service
from app.modules.materials import extraction
from app.modules.materials import service as materials_service
from app.modules.materials.convert import clean
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

# describe_image (9.4): A2.4 подключит настоящую одной строкой. Пока его нет — описание
# пропускается, даже если оно включено настройкой MATERIAL_DESCRIBE_IMAGES.
DESCRIBE_IMAGE: DescribeImage | None = None
# Сколько ждать описание картинки. Не дождались — описание пустое, текст всё равно готов.
DESCRIBE_TIMEOUT_S = 60
# Длиннее описание не бывает; больше — ошибка модели, а не скриншот.
DESCRIPTION_MAX_CHARS = 20_000

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
    await extract_material(
        file_id,
        sessionmaker=sessionmaker,
        storage=storage,
        events=events,
        settings=get_settings(),
        describe=describer(),
    )


def describer() -> DescribeImage | None:
    """Чем описывать скриншоты: describe_image, если описание включено и уже есть (A2.4)."""
    return DESCRIBE_IMAGE if get_settings().material_describe_images else None


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
    settings: Settings,
    extract: Extract = extraction.extract,
    describe: DescribeImage | None = None,
) -> None:
    """Извлекает текст материала и записывает итог, если файл с тех пор не менялся.

    Сначала задача ждёт свободного места (extraction.slot) и только потом берёт материал
    в работу (claim): так от взятия до итога проходит не больше срока разбора или описания,
    и фоновая проверка не отправит материал снова, пока задание работает. В той же
    транзакции, что и claim, читается файл: прочитанное содержимое — не старше метки, с
    которой сверяется запись итога. Извлечение — без соединения с базой. Пока оно шло, файл
    могли заменить, удалить или перенести из materials/ — тогда итог не записывается и
    события нет: новую версию обработает своё задание. После записи — material.ready с путём
    файла на этот момент. Скриншот описывает describe, если он передан, — уже освободив место.
    """
    async with extraction.slot():
        async with sessionmaker() as session:
            token = await materials_service.claim(session, file_id)
            file = await projects_service.get_file(session, file_id) if token else None
            await session.commit()
        if token is None or file is None:
            return
        outcome, image = await _outcome(file, storage, extract)
    if describe is not None and image is not None:
        description = await _describe(sessionmaker, settings, file, image, describe)
        outcome = replace(outcome, description=description)
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


async def _outcome(file: File, storage: Storage, extract: Extract) -> tuple[Outcome, bytes | None]:
    """Итог извлечения и байты картинки, если это скриншот, — для описания. Ошибка —
    понятное сообщение студенту, подробности — в лог."""
    try:
        if file.kind == "text":
            content: str | bytes = file.content or ""
        else:
            stream = await projects_service.open_binary(storage, file)
            content = b"".join([chunk async for chunk in stream])
        extracted = await extract(file.mime, content)
    except ExtractionFailed as failed:
        logger.warning("material_extraction_failed", file_id=str(file.id), **failed.detail)
        return Outcome(status="failed", error=failed.message), None
    except AppError as error:
        # Blob потерян (open_binary уже записал в лог): помогает только загрузить заново.
        return Outcome(status="failed", error=error.message), None
    # Exception: сбой в нашем коде не должен оставить материал pending навсегда — фоновая
    # проверка отправляла бы его снова и снова.
    except Exception:
        logger.exception("material_extraction_crashed", file_id=str(file.id))
        return Outcome(status="failed", error=FAILED_MESSAGE), None
    image = content if extracted.method == "image" and isinstance(content, bytes) else None
    outcome = Outcome(
        status="ready", text=extracted.text, method=extracted.method, pages=extracted.pages
    )
    return outcome, image


async def _describe(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    file: File,
    data: bytes,
    describe: DescribeImage,
) -> str | None:
    """Описание скриншота от vision-модели. Сбой или нет ответа — None (9.4): картинка
    остаётся материалом без описания, и ИИ может посмотреть её сам (get_image).

    Описывает на своём ключе владельца проекта, если он есть; иначе — на ключе сервиса, и
    расход идёт в учёт владельца (architecture.md 5). Проект уже удалили — описывать некому.
    """
    async with sessionmaker() as session:
        project = await projects_service.get_project(session, file.project_id)
        owner_id = None if project is None else project.owner_id
        user_key = (
            None if owner_id is None else await llm_service.usable_key(session, owner_id, settings)
        )
    if owner_id is None:
        return None
    try:
        async with asyncio.timeout(DESCRIBE_TIMEOUT_S):
            described = await describe(data, file.mime or "", user_key=user_key)
    # Exception: describe_image при сбое модели бросает исключение (9.4), а срок — TimeoutError.
    except Exception as error:
        logger.warning(
            "material_describe_failed", file_id=str(file.id), error_type=type(error).__name__
        )
        return None
    usage = described.usage
    if user_key is None:
        async with sessionmaker() as session:
            await llm_service.record_usage(
                session, owner_id, None, usage.tokens_in, usage.tokens_out, usage.cost
            )
            await session.commit()
    logger.info(
        "material_described",
        file_id=str(file.id),
        model=usage.model,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        cost=str(usage.cost),
    )
    # Как у документов: без нулевых символов и одиночных суррогатов, иначе итог не запишется,
    # а фоновая проверка снова и снова заказывала бы платное описание.
    text = clean(described.text)
    return extraction.truncated(text, len(text), DESCRIPTION_MAX_CHARS) or None


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
