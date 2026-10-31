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
