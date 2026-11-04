"""Текст материалов проекта (architecture.md 5, 9.1)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.db import DbSession
from app.modules.materials import service
from app.modules.materials.dependencies import OwnedMaterial
from app.modules.materials.schemas import (
    MATERIAL_TEXT_DEFAULT_LIMIT,
    MATERIAL_TEXT_MAX_LIMIT,
    MaterialTextOut,
)

router = APIRouter(prefix="/projects", tags=["materials"])


@router.get("/{pid}/material-text")
async def get_material_text(
    material: OwnedMaterial,
    session: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MATERIAL_TEXT_MAX_LIMIT)] = MATERIAL_TEXT_DEFAULT_LIMIT,
) -> MaterialTextOut:
    """Что ИИ видит в материале: статус извлечения и кусок текста.

    Пока текст извлекается и если не вышло — тоже 200, text — null. Чужой проект, нет файла,
    папка или файл не из materials/ — 404.
    """
    return await service.material_text(session, material, offset=offset, limit=limit)
