"""Проверки отчёта: id проверок, находка и итог (architecture.md 9.4, docs/checks.md)."""

from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field

# Однозначные проверки из docs/checks.md, часть 1, — в порядке сводки: в нём же идут
# находки, если у них одно место.
CheckId = Literal[
    "build-failed",
    "section-empty",
    "placeholder",
    "caption-missing",
    "caption-format",
    "ref-broken",
    "ref-missing",
    "ref-after",
    "listing-too-long",
    "file-missing",
    "code-not-in-materials",
    "number-not-in-materials",
    "heading-format",
    "list-format",
    "formula-format",
    "bib-order",
    "manual-formatting",
    "title-empty",
    "text-overflow",
    "missing-glyph",
]
CHECK_IDS: tuple[CheckId, ...] = get_args(CheckId)
# Проверки по итогу и логу сборки: им нужна сборка текущих файлов.
PDF_CHECKS: frozenset[CheckId] = frozenset({"build-failed", "text-overflow", "missing-glyph"})

CheckLevel = Literal["error", "warning"]
# Где исправлять: в файле, в панели сборки, в профиле или в полях работы.
CheckPlace = Literal["file", "build", "profile", "fields"]


class CheckFinding(BaseModel):
    """Одно нарушение: что не так и где это исправить."""

    check: CheckId = Field(description="id проверки из docs/checks.md")
    level: CheckLevel
    message: str = Field(description="Текст для студента, со значениями")
    file: str | None = Field(description="Путь в проекте, как у ошибок сборки; null — без файла")
    line: int | None = Field(description="Строка с 1; null — весь файл или без файла")
    place: CheckPlace = Field(
        description="Где исправлять: file — в файле, build — в панели сборки, "
        "profile или fields — в профиле или полях работы"
    )
    field: str | None = Field(
        description="Ключ поля профиля (group_name) или проекта (teacher) при place "
        "profile или fields, иначе null"
    )


class CheckResult(BaseModel):
    """Итог проверок проекта: находки по месту и что с проверками по PDF."""

    findings: list[CheckFinding] = Field(
        description="Сначала без файла, потом файлы в порядке подключения в отчёт, "
        "в файле — по строке"
    )
    errors_count: int
    warnings_count: int
    build_id: UUID | None = Field(
        description="Сборка, по которой проверен PDF или которую ждали; null — проверок "
        "по PDF у шаблона нет"
    )
    pdf_checked: bool = Field(
        description="Проверки по PDF сделаны или их у шаблона нет; false — сборка ещё "
        "идёт, находок по PDF в ответе нет: повторите запрос"
    )
