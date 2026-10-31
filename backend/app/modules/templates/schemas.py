"""Схемы шаблонов для API: то, что из template.yaml (9.5) видно пользователю.

ai_rules сюда не входят: это правила для агента, наружу они не отдаются.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.projects.schemas import ProjectKind

FieldType = Literal["string", "int", "text", "select"]


class TemplateField(BaseModel):
    """Поле, которое спрашивается при создании проекта."""

    key: str
    label: str
    type: FieldType
    required: bool
    default: str | int | None
    options: list[str] = Field(description="Варианты для type=select; у остальных — пустой список")


class TemplateSection(BaseModel):
    id: str
    title: str
    file: str
    required: bool
    guide: str = Field(description="Что должно быть в разделе")


class TemplateSummary(BaseModel):
    slug: str
    version: int
    kind: ProjectKind
    title: str
    discipline: str | None


class TemplateDetail(TemplateSummary):
    fields: list[TemplateField]
    sections: list[TemplateSection]


class TemplateList(BaseModel):
    items: list[TemplateSummary]
