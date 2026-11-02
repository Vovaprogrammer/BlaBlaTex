"""Шаблоны: список и поля для формы создания проекта. Без входа — в них нет данных пользователей."""

from fastapi import APIRouter

from app.core.errors import AppError, ErrorCode
from app.modules.templates.dependencies import Templates
from app.modules.templates.registry import Template
from app.modules.templates.schemas import (
    TemplateDetail,
    TemplateField,
    TemplateList,
    TemplateSection,
    TemplateSummary,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _summary(template: Template) -> TemplateSummary:
    return TemplateSummary.model_validate(template.manifest, from_attributes=True)


def _detail(template: Template) -> TemplateDetail:
    # Поля перечислены явно: ai_rules и checks — для агента и проверок, наружу не отдаются.
    manifest = template.manifest
    return TemplateDetail(
        **_summary(template).model_dump(),
        fields=[TemplateField.model_validate(f, from_attributes=True) for f in manifest.fields],
        sections=[
            TemplateSection.model_validate(s, from_attributes=True) for s in manifest.sections
        ],
    )


@router.get("")
async def list_templates(templates: Templates) -> TemplateList:
    return TemplateList(items=[_summary(template) for template in templates.values()])


@router.get("/{slug}")
async def get_template(slug: str, templates: Templates) -> TemplateDetail:
    """Шаблон с полями для формы создания проекта и разделами отчёта."""
    template = templates.get(slug)
    if template is None:
        raise AppError(ErrorCode.NOT_FOUND, "Шаблон не найден", 404)
    return _detail(template)
