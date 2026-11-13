"""Проект для примеров из docs/checks.md: шаблон mtuci-lab, meta.tex как meta.sample.tex
и материалы из раздела «Проект для примеров».

    found = run(CHECK, {"sections/progress.tex": PROGRESS})
    assert places(found) == [("sections/progress.tex", 3)]
"""

from collections.abc import Collection, Mapping
from pathlib import Path

from app.core.config import TEMPLATES_DIR
from app.modules.checks.context import BuildOutcome, MaterialSource, SectionSpec, Snapshot
from app.modules.checks.engine import check_project
from app.modules.checks.schemas import CheckFinding, CheckId
from app.modules.templates.registry import load_templates

FIXTURES = Path(__file__).parent / "fixtures" / "checks"
LAB = TEMPLATES_DIR / "mtuci-lab"
MANIFEST = load_templates(TEMPLATES_DIR)["mtuci-lab"].manifest

MAIN_PY = (FIXTURES / "main.py").read_text(encoding="utf-8")
OUTPUT_TXT = (FIXTURES / "output.txt").read_text(encoding="utf-8")
RUN_PNG_DESCRIPTION = (
    "Окно терминала с выводом программы поиска: „Линейный поиск: индекс 7, 0.0042 с“, "
    "„Бинарный поиск: индекс 7, 0.0038 с“"
)
METOD_TEXT = (
    "Цель работы: изучить методы поиска элемента в массиве.\n"
    "Задание\n1. Реализовать линейный поиск. 2. Реализовать бинарный поиск. "
    "3. Сравнить время поиска на массивах из 1000 и 10000 элементов.\n"
    "Вариант 11: дополнительно реализовать поиск с барьером.\n"
    "Вариант 12: дополнительно реализовать интерполяционный поиск.\n"
)
MATERIALS = (
    MaterialSource("materials/main.py", "ready", MAIN_PY, None),
    MaterialSource("materials/output.txt", "ready", OUTPUT_TXT, None),
    MaterialSource("materials/run.png", "ready", "", RUN_PNG_DESCRIPTION),
    MaterialSource("materials/metod.pdf", "ready", METOD_TEXT, None),
)
# Значения полей проекта и профиля — те же, что в meta.sample.tex.
VALUES = (
    "Структуры и алгоритмы обработки данных",
    "2",
    "Методы поиска в массиве",
    "12",
    "доц. Петров П. П.",
    "Лабораторная работа",
    "Смирнов",
    "Илья",
    "Андреевич",
    "БВТ0000",
    "Информационные технологии",
    "Математическая кибернетика и информационные технологии",
)


def lab_files() -> dict[str, str]:
    """Текстовые файлы нового проекта из mtuci-lab: main.tex, разделы, meta.tex и код."""
    files = {
        path.relative_to(LAB).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(LAB.rglob("*.tex"))
        if path.name != "meta.sample.tex"
    }
    files["meta.tex"] = (LAB / "meta.sample.tex").read_text(encoding="utf-8")
    files["materials/main.py"] = MAIN_PY
    files["materials/output.txt"] = OUTPUT_TXT
    return files


def snapshot(
    changes: Mapping[str, str | None] | None = None,
    *,
    materials: tuple[MaterialSource, ...] = MATERIALS,
    binary: Collection[str] = ("materials/run.png", "materials/metod.pdf"),
) -> Snapshot:
    """Проект для примеров; changes — файлы, которые заменить (None — удалить)."""
    texts = lab_files()
    for path, text in (changes or {}).items():
        if text is None:
            texts.pop(path, None)
        else:
            texts[path] = text
    return Snapshot(
        main_file=MANIFEST.main,
        sections=tuple(
            SectionSpec(section.title, section.file, section.required)
            for section in MANIFEST.sections
        ),
        texts=texts,
        files=frozenset({*texts, *binary}),
        materials=materials,
        values=VALUES,
        field_keys=frozenset(field.key for field in MANIFEST.fields),
    )


def run(
    check: CheckId,
    changes: Mapping[str, str | None] | None = None,
    *,
    build: BuildOutcome | None = None,
    project: Snapshot | None = None,
) -> list[CheckFinding]:
    """Находки одной проверки на проекте для примеров."""
    return check_project(project or snapshot(changes), {check}, build)


def places(findings: list[CheckFinding]) -> list[tuple[str | None, int | None]]:
    return [(finding.file, finding.line) for finding in findings]
