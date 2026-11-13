"""Проверки отчёта целиком: какие запускать, уровень и порядок находок (architecture.md 9.4).

check_project — чистая функция от снимка проекта и итога сборки: ни базы, ни хранилища.
Её вызывают и настоящая ProjectTools (через checks/service.py), и фейк для тестов.
"""

from collections.abc import Callable, Collection, Iterable

from app.modules.checks import elements, formatting, materials, pdf, structure
from app.modules.checks.context import BuildOutcome, Context, Found, Snapshot
from app.modules.checks.schemas import (
    CHECK_IDS,
    PDF_CHECKS,
    CheckFinding,
    CheckId,
    CheckLevel,
    CheckPlace,
)

type Rule = Callable[[Context], Iterable[Found]]

# Проверка → уровень и правило (сводка docs/checks.md).
RULES: dict[CheckId, tuple[CheckLevel, Rule]] = {
    "build-failed": ("error", pdf.build_failed),
    "section-empty": ("error", structure.section_empty),
    "placeholder": ("error", structure.placeholder),
    "caption-missing": ("error", elements.caption_missing),
    "caption-format": ("warning", elements.caption_format),
    "ref-broken": ("error", elements.ref_broken),
    "ref-missing": ("warning", elements.ref_missing),
    "ref-after": ("warning", elements.ref_after),
    "listing-too-long": ("warning", elements.listing_too_long),
    "file-missing": ("error", materials.file_missing),
    "code-not-in-materials": ("warning", materials.code_not_in_materials),
    "number-not-in-materials": ("warning", materials.number_not_in_materials),
    "heading-format": ("warning", formatting.heading_format),
    "list-format": ("warning", formatting.list_format),
    "formula-format": ("warning", formatting.formula_format),
    "bib-order": ("warning", formatting.bib_order),
    "manual-formatting": ("warning", formatting.manual_formatting),
    "title-empty": ("warning", structure.title_empty),
    "text-overflow": ("warning", pdf.text_overflow),
    "missing-glyph": ("warning", pdf.missing_glyph),
}
# Находки без файла: сначала сборка, потом профиль, потом поля работы.
_PLACES: tuple[CheckPlace, ...] = ("build", "profile", "fields", "file")


def check_project(
    snapshot: Snapshot, checks: Collection[CheckId], build: BuildOutcome | None
) -> list[CheckFinding]:
    """Находки проверок checks по порядку (9.4). build — законченная сборка текущих файлов;
    None — проверки по PDF не запускаются."""
    context = Context(snapshot, build)
    found: list[Found] = []
    for check in CHECK_IDS:
        if check not in checks or (build is None and check in PDF_CHECKS):
            continue
        found.extend(RULES[check][1](context))
    order = {path: index for index, path in enumerate(context.report.files)}
    rank = {check: index for index, check in enumerate(CHECK_IDS)}

    def key(item: tuple[int, Found]) -> tuple[int, int, str, int, int, int, int]:
        sequence, finding = item
        if finding.file is None:
            return (0, _PLACES.index(finding.place), "", 0, 0, rank[finding.check], sequence)
        file_rank = order.get(finding.file, len(order))
        line = finding.line or 0
        return (1, file_rank, finding.file, line, finding.position, rank[finding.check], sequence)

    return [_finding(finding) for _, finding in sorted(enumerate(found), key=key)]


def _finding(found: Found) -> CheckFinding:
    return CheckFinding(
        check=found.check,
        level=RULES[found.check][0],
        message=found.message,
        file=found.file,
        line=found.line,
        place=found.place,
        field=found.field,
    )
