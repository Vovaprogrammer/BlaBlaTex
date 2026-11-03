"""Материалы: состояние извлечения текста (architecture.md 5). Таблица material_text — только здесь.

Строки создаёт, сбрасывает и удаляет сервис файлов проекта — в той же транзакции, когда
материал появился в materials/, изменился или ушёл оттуда. Сами файлы модуль не меняет.
Извлечение текста и описание картинок — B2.7.
"""

import uuid
from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.materials.models import MaterialText


async def mark_pending(session: AsyncSession, file_ids: Collection[uuid.UUID]) -> None:
    """Материалы появились или их содержимое изменилось: текст нужно извлечь заново.

    Строки нет — создаётся со статусом pending, есть — снова pending, а прежние текст,
    описание и ошибка стираются: ИИ не прочитает текст старой версии файла.
    Не коммитит: вызывается внутри изменения файлов.
    """
    if not file_ids:
        return
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


async def keep_or_add(session: AsyncSession, file_ids: Collection[uuid.UUID]) -> None:
    """Файлы перенесены в materials/ или внутри неё: у новых материалов — строка pending.

    Уже извлечённый текст остаётся: перенос не меняет содержимое. Не коммитит.
    """
    if not file_ids:
        return
    statement = insert(MaterialText).values(
        [{"file_id": file_id, "status": "pending"} for file_id in file_ids]
    )
    await session.execute(statement.on_conflict_do_nothing(index_elements=[MaterialText.file_id]))


async def forget(session: AsyncSession, file_ids: Collection[uuid.UUID]) -> None:
    """Файлы перенесены из materials/ и больше не материалы. Не коммитит.

    Удалённый файл забывать не нужно: строку удаляет сама база (ON DELETE CASCADE).
    """
    if file_ids:
        await session.execute(delete(MaterialText).where(MaterialText.file_id.in_(file_ids)))
