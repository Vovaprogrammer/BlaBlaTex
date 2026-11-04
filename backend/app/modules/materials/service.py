"""Материалы: состояние извлечения текста (architecture.md 5). Таблица material_text — только здесь.

Строки создаёт, сбрасывает и удаляет сервис файлов проекта — в той же транзакции, когда
материал появился в materials/, изменился или ушёл оттуда. Итог извлечения записывает задача
воркера (materials/tasks.py), читают его ProjectTools агента и REST (statuses). Сами файлы
модуль не меняет.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.materials.models import MaterialText
from app.modules.materials.schemas import MaterialMethod

# Материал ждёт дольше — его задание, видимо, потерялось (очередь была недоступна, воркер
# упал): фоновая проверка воркера ставит его в очередь снова. Больше, чем идёт одно
# извлечение (до 60 с), иначе задание, которое ещё работает, потеряло бы свой итог.
REQUEUE_AFTER = timedelta(minutes=2)
# Сколько материалов фоновая проверка отправляет за раз.
REQUEUE_BATCH = 100


@dataclass(frozen=True)
class Outcome:
    """Итог извлечения текста одного материала."""

    status: Literal["ready", "failed"]
    text: str | None = None
    method: MaterialMethod | None = None
    pages: int | None = None
    description: str | None = None
    error: str | None = None


async def statuses(
    session: AsyncSession, file_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, MaterialText]:
    """Итог извлечения текста по материалам: id файла → строка material_text."""
    if not file_ids:
        return {}
    rows = await session.scalars(select(MaterialText).where(MaterialText.file_id.in_(file_ids)))
    return {row.file_id: row for row in rows}


async def mark_pending(session: AsyncSession, file_ids: Collection[uuid.UUID]) -> list[uuid.UUID]:
    """Материалы появились или их содержимое изменилось: текст нужно извлечь заново.

    Строки нет — создаётся со статусом pending, есть — снова pending, а прежние текст,
    описание и ошибка стираются: ИИ не прочитает текст старой версии файла. Возвращает
    материалы, которые ждут извлечения, — все переданные. Не коммитит: вызывается внутри
    изменения файлов.
    """
    if not file_ids:
        return []
    statement = insert(MaterialText).values(
        [{"file_id": file_id, "status": "pending"} for file_id in file_ids]
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[MaterialText.file_id],
            set_={
                "status": "pending",
                "text": None,
                "method": None,
                "pages": None,
                "description": None,
                "error": None,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    return list(file_ids)


async def keep_or_add(session: AsyncSession, file_ids: Collection[uuid.UUID]) -> list[uuid.UUID]:
    """Файлы перенесены в materials/ или внутри неё: у новых материалов — строка pending.

    Уже извлечённый текст остаётся: перенос не меняет содержимое. Возвращает новые
    материалы — их текст нужно извлечь. Не коммитит.
    """
    if not file_ids:
        return []
    statement = insert(MaterialText).values(
        [{"file_id": file_id, "status": "pending"} for file_id in file_ids]
    )
    added = await session.scalars(
        statement.on_conflict_do_nothing(index_elements=[MaterialText.file_id]).returning(
            MaterialText.file_id
        )
    )
    return list(added)


async def forget(session: AsyncSession, file_ids: Collection[uuid.UUID]) -> None:
    """Файлы перенесены из materials/ и больше не материалы. Не коммитит.

    Удалённый файл забывать не нужно: строку удаляет сама база (ON DELETE CASCADE).
    """
    if file_ids:
        await session.execute(delete(MaterialText).where(MaterialText.file_id.in_(file_ids)))


async def claim(session: AsyncSession, file_id: uuid.UUID) -> datetime | None:
    """Задача извлечения берёт материал в работу: у строки pending — новая метка updated_at.

    Итог запишется, только если метка останется той же (save_result): новая загрузка,
    повторное задание или повторная постановка в очередь её меняют. Строки нет (файл удалён
    или ушёл из materials/) или текст уже извлечён — None. Не коммитит; строка заблокирована
    до commit — читать файл нужно после claim в той же транзакции.
    """
    token: datetime | None = await session.scalar(
        update(MaterialText)
        .where(MaterialText.file_id == file_id, MaterialText.status == "pending")
        .values(updated_at=func.clock_timestamp())
        .returning(MaterialText.updated_at)
    )
    return token


async def save_result(
    session: AsyncSession, file_id: uuid.UUID, token: datetime, outcome: Outcome
) -> bool:
    """Записывает итог, если строку не меняли с claim (token). Иначе итог — о старой
    версии файла или его уже пишет другое задание: False. Не коммитит."""
    saved = await session.scalar(
        update(MaterialText)
        .where(
            MaterialText.file_id == file_id,
            MaterialText.status == "pending",
            MaterialText.updated_at == token,
        )
        .values(
            status=outcome.status,
            text=outcome.text,
            method=outcome.method,
            pages=outcome.pages,
            description=outcome.description,
            error=outcome.error,
            updated_at=func.clock_timestamp(),
        )
        .returning(MaterialText.file_id)
    )
    return saved is not None


async def requeue_stale(session: AsyncSession) -> list[uuid.UUID]:
    """Материалы, которые ждут извлечения дольше REQUEUE_AFTER, — их нужно отправить снова.

    Метка updated_at у них обновляется: следующая проверка не отправит их ещё раз, а
    задание, взятое до этого, не запишет итог. Строки, которые сейчас меняет другая
    транзакция, пропускаются. Не коммитит.
    """
    stale = (
        select(MaterialText.file_id)
        .where(
            MaterialText.status == "pending",
            MaterialText.updated_at < func.now() - REQUEUE_AFTER,
        )
        .order_by(MaterialText.updated_at)
        .limit(REQUEUE_BATCH)
        .with_for_update(skip_locked=True)
    )
    requeued = await session.scalars(
        update(MaterialText)
        .where(MaterialText.file_id.in_(stale))
        .values(updated_at=func.clock_timestamp())
        .returning(MaterialText.file_id)
    )
    return list(requeued)
