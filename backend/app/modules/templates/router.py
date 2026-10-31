"""Реестр шаблонов. Пока заглушки: логику добавит A1.2."""

from fastapi import APIRouter

from app.core.errors import not_implemented
from app.modules.templates.schemas import TemplateDetail, TemplateList

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("")
async def list_templates() -> TemplateList:
    raise not_implemented()


@router.get("/{slug}")
async def get_template(slug: str) -> TemplateDetail:
    """Шаблон с полями для формы создания проекта и разделами отчёта."""
    raise not_implemented()
