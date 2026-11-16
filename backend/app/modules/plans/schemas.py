"""Схемы плана отчёта (architecture.md 9.1 «План отчёта», 9.4)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.text import NoNul

PlanStatus = Literal["draft", "confirmed"]

NOTE_MAX_LENGTH = 2000
SECTIONS_MAX = 100
SECTION_MATERIALS_MAX = 500


class PlanSection(BaseModel):
    section_id: str = Field(description="id раздела из template.yaml")
    title: str = Field(description="Название раздела из шаблона")
    materials: list[str] = Field(
        description="Пути материалов из materials/ в заданном порядке; один материал может "
        "быть в нескольких разделах"
    )
    # Заметку пишет студент или ИИ по материалам студента: в repr и логи она не попадает.
    note: str = Field(
        repr=False,
        description="Что будет написано в разделе и чего не хватает в материалах; "
        f"до {NOTE_MAX_LENGTH} символов, может быть пустой",
    )


class ReportPlan(BaseModel):
    """План отчёта: разделы шаблона по порядку и какие материалы в какой."""

    sections: list[PlanSection] = Field(
        description="Все разделы шаблона проекта в его порядке, каждый один раз"
    )
    unassigned: list[str] = Field(
        description="Материалы проекта, которых нет ни в одном разделе, по пути"
    )


class PlanOut(BaseModel):
    plan: ReportPlan
    status: PlanStatus = Field(
        description="draft — черновик; confirmed — подтверждён, по нему пишется отчёт"
    )
    updated_at: datetime


PlanNote = Annotated[str, StringConstraints(max_length=NOTE_MAX_LENGTH), NoNul]
MaterialPath = Annotated[str, NoNul]


class PlanSectionUpdate(BaseModel):
    section_id: Annotated[str, NoNul] = Field(description="id раздела из template.yaml")
    materials: list[MaterialPath] = Field(
        default_factory=list,
        max_length=SECTION_MATERIALS_MAX,
        description="Пути материалов из materials/; в разделе каждый не больше одного раза",
    )
    note: PlanNote = Field(default="", repr=False)


class PlanUpdate(BaseModel):
    """Тело PUT /plan: разделы плана. title и unassigned считает сервер."""

    sections: list[PlanSectionUpdate] = Field(
        max_length=SECTIONS_MAX,
        description="Разделы плана; раздела шаблона нет в списке — он пустой",
    )
