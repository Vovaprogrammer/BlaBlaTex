"""Эталонные отчёты templates/_examples/ (T2.3): проверки бэкенда не находят в них ни ошибок,
ни предупреждений, а настоящий компилятор собирает их без вылезаний за поле.

Эталон — проект целиком, как его видят проверки: файлы отчёта, meta.tex из meta.sample.tex и
материалы из materials/. Сборка — с пометкой compiler: uv run pytest -m compiler.
"""

import re
from collections.abc import AsyncIterator

import pytest

from app.core.config import TEMPLATES_DIR, Settings
from app.modules.builds.compiler import CompilerClient, CompilerError, create_http_client
from app.modules.builds.log_parser import parse_log
from app.modules.builds.service import pack_project
from app.modules.checks.context import BuildOutcome, MaterialSource, SectionSpec, Snapshot
from app.modules.checks.engine import check_project
from app.modules.checks.schemas import CheckFinding, CheckId
from app.modules.projects.paths import is_text_file_type
from app.modules.templates.registry import load_templates

EXAMPLES_DIR = TEMPLATES_DIR / "_examples"
EXAMPLES = sorted(path.name for path in EXAMPLES_DIR.iterdir() if path.is_dir())
MANIFEST = load_templates(TEMPLATES_DIR)["mtuci-lab"].manifest
PDF_CHECKS: frozenset[CheckId] = frozenset({"build-failed", "text-overflow", "missing-glyph"})
SOURCE_CHECKS = frozenset(MANIFEST.checks) - PDF_CHECKS

# Числа, которые отчёт посчитал из материалов: отношения, сравнения, пересчёт единиц.
# number-not-in-materials их в материалах не находит — предупреждение ожидаемое, решает
# студент (docs/checks.md). Список полный: новое число в эталоне без записи здесь — падение.
DERIVED_NUMBERS: dict[str, set[str]] = {
    "lab-algorithms": {"3,8", "4,5", "368"},
    "lab-circuit": {"482"},
    "lab-logic": set(),
    "lab-network": set(),
    "lab-sql": set(),
}

_DEFINITION = re.compile(r"^\\def\\bbt[A-Za-z]+\{(.*)\}\s*$", re.MULTILINE)
_NUMBERS = re.compile(r"^Чисел (.+?) нет в ваших материалах")


def example_files(name: str) -> dict[str, bytes]:
    """Все файлы эталона, как в проекте: meta.sample.tex становится meta.tex."""
    root = EXAMPLES_DIR / name
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    files["meta.tex"] = files.pop("meta.sample.tex")
    return files


def example_snapshot(name: str) -> Snapshot:
    files = example_files(name)
    texts = {
        path: data.decode("utf-8").replace("\r\n", "\n")
        for path, data in files.items()
        if is_text_file_type(path)
    }
    materials = tuple(
        MaterialSource(path, "ready", texts.get(path, ""), None)
        for path in files
        if path.startswith("materials/")
    )
    return Snapshot(
        main_file=MANIFEST.main,
        sections=tuple(
            SectionSpec(section.title, section.file, section.required)
            for section in MANIFEST.sections
        ),
        texts=texts,
        files=frozenset(files),
        materials=materials,
        values=tuple(_DEFINITION.findall(texts["meta.tex"])),
        field_keys=frozenset(field.key for field in MANIFEST.fields),
    )


def derived_numbers(findings: list[CheckFinding]) -> set[str]:
    numbers: set[str] = set()
    for finding in findings:
        match = _NUMBERS.match(finding.message)
        assert match is not None, finding.message
        numbers.update(match[1].split("; "))
    return numbers


def test_examples_exist() -> None:
    assert EXAMPLES == sorted(DERIVED_NUMBERS)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_follows_template(name: str) -> None:
    # Эталон — проект из mtuci-lab: тот же main.tex и файлы всех разделов, в том числе
    # необязательных. Правка шаблона без правки эталонов — падение, а не тихое расхождение.
    files = example_files(name)
    assert files[MANIFEST.main] == (TEMPLATES_DIR / "mtuci-lab" / MANIFEST.main).read_bytes()
    assert {section.file for section in MANIFEST.sections} <= set(files)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_passes_source_checks(name: str) -> None:
    found = check_project(example_snapshot(name), set(SOURCE_CHECKS), None)

    numbers = [f for f in found if f.check == "number-not-in-materials"]
    other = [(f.check, f.file, f.line, f.message) for f in found if f not in numbers]
    assert other == []
    assert derived_numbers(numbers) == DERIVED_NUMBERS[name]


@pytest.fixture
async def compiler() -> AsyncIterator[CompilerClient]:
    url = Settings(app_env="test").compiler_base_url
    async with create_http_client(url) as http:
        client = CompilerClient(http)
        try:
            await client.version()
        except CompilerError:
            pytest.fail(
                f"Компилятор не отвечает на {url}. Запустите docker compose up -d.", pytrace=False
            )
        yield client


@pytest.mark.compiler
@pytest.mark.parametrize("name", EXAMPLES)
async def test_example_builds_without_overflow(compiler: CompilerClient, name: str) -> None:
    files = example_files(name)
    archive = pack_project(sorted(files.items()))

    result = await compiler.compile(archive, main=MANIFEST.main, engine=MANIFEST.engine)

    project = example_snapshot(name)
    log = parse_log(result.log, project.texts, MANIFEST.engine)
    errors = len([error for error in log.errors if error.severity == "error"])
    found = check_project(project, set(PDF_CHECKS), BuildOutcome(result.status, errors, result.log))
    assert result.status == "ok"
    # text-overflow ловит и абзацы, и таблицы, и формулы шире поля.
    assert [(f.check, f.file, f.line, f.message) for f in found] == []


def test_examples_are_not_templates() -> None:
    # Папки на _ реестр пропускает: эталоны с картинками не копируются в проекты студентов.
    assert EXAMPLES_DIR.name.startswith("_")
    assert not set(EXAMPLES) & set(load_templates(TEMPLATES_DIR))
