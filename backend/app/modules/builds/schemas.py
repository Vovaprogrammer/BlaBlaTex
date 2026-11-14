"""Схемы сборок: статус, ошибки LaTeX и артефакты."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.projects.schemas import Engine

BuildStatus = Literal["queued", "running", "ok", "error", "timeout"]


class BuildError(BaseModel):
    """Ошибка или предупреждение из лога LaTeX (9.4)."""

    file: str | None = Field(description="Путь в проекте; null, если LaTeX его не назвал")
    line: int | None
    message: str
    context: str = Field(description="До 10 строк до и после места ошибки, с номерами строк")
    severity: Literal["error", "warning"]


class BuildOut(BaseModel):
    id: UUID
    project_id: UUID
    status: BuildStatus
    engine: Engine
    pages: int | None
    duration_ms: int | None
    warnings_count: int
    errors: list[BuildError]
    has_pdf: bool = Field(description="PDF можно скачать: GET /builds/{bid}/pdf")
    created_at: datetime


class SyncTexSource(BaseModel):
    """Место в файле проекта, где написан текст из PDF."""

    path: str = Field(description="Путь файла в проекте (9.8)")
    line: int = Field(ge=1, description="Номер строки, от 1; как в файле на момент сборки")


class SyncTexEditOut(BaseModel):
    """Что написано в месте страницы PDF (architecture.md 9.1, «SyncTeX»)."""

    source: SyncTexSource | None = Field(
        description="null — здесь нет текста студента: титульный лист, номер страницы, "
        "пустое место под текстом, текст класса или TeX Live, страницы нет в PDF"
    )


class SyncTexBox(BaseModel):
    """Прямоугольник на странице PDF.

    Пункты PDF (1/72 дюйма) от левого верхнего угла страницы, ось y — вниз. В пиксели экрана —
    одним множителем: ширина страницы на экране в пикселях / ширина страницы в пунктах.
    """

    page: int = Field(ge=1, description="Номер страницы, от 1")
    x: float = Field(ge=0, description="Левый край")
    y: float = Field(ge=0, description="Верхний край")
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class SyncTexViewOut(BaseModel):
    """Где в PDF строка файла (architecture.md 9.1, «SyncTeX»)."""

    boxes: list[SyncTexBox] = Field(
        description="Первый — самый точный. Пусто — строки нет в PDF: meta.tex, строка "
        "\\bbtTitlePage, файл, которого не было в сборке"
    )
