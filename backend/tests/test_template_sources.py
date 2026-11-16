"""Исходники шаблона (T1.4): разделы подключены в main.tex, meta.sample.tex совпадает с полями.

Настоящие шаблоны проверяет test_template_registry.py::test_repository_templates_are_valid,
эталоны — test_template_examples.py. Здесь — что сломанный шаблон эти проверки не проходит.
"""

import shutil
from pathlib import Path

import pytest

from app.modules.templates.registry import load_templates
from tests.helpers import TEMPLATE_FIXTURES
from tests.template_sources import backend_macros, sample_meta_problems, source_problems

SECTIONS_INPUT = "\\input{sections/goal}\n\\input{sections/conclusion}\n"


@pytest.fixture
def lab(tmp_path: Path) -> Path:
    """Копия фикстуры test-lab, которую тест может портить."""
    target = tmp_path / "templates" / "test-lab"
    shutil.copytree(TEMPLATE_FIXTURES / "test-lab", target)
    return target


def problems(lab: Path) -> list[str]:
    return source_problems(lab, load_templates(lab.parent)["test-lab"])


def replace_in(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_fixture_has_no_problems(lab: Path) -> None:
    assert problems(lab) == []


@pytest.mark.parametrize(
    "inputs",
    [
        "\\input{sections/goal}\n",
        "\\input{sections/goal}\n% \\input{sections/conclusion}\n",
        "\\input{sections/goal}\n\\iffalse\\fi %\\input{sections/conclusion}\n",
    ],
    ids=["removed", "commented out", "comment after code"],
)
def test_section_not_included(lab: Path, inputs: str) -> None:
    replace_in(lab / "main.tex", SECTIONS_INPUT, inputs)

    assert problems(lab) == [
        "test-lab/main.tex: sections.1.file: sections/conclusion.tex не подключён через "
        "\\input — раздела «Выводы» не будет в PDF"
    ]


@pytest.mark.parametrize(
    "inputs",
    [
        "\\input{./sections/goal.tex}\n\\include{sections/conclusion}\n",
        "\\input{body}\n",
    ],
    ids=["path forms", "through another file"],
)
def test_section_included(lab: Path, inputs: str) -> None:
    replace_in(lab / "main.tex", SECTIONS_INPUT, inputs)
    (lab / "body.tex").write_text(SECTIONS_INPUT, encoding="utf-8")

    assert problems(lab) == []


def test_renamed_field_key(lab: Path) -> None:
    # Ключ переименовали, а meta.sample.tex — нет: check-template собрал бы шаблон со старым
    # макросом, а у студента его не будет.
    replace_in(lab / "template.yaml", "key: variant", "key: option")

    assert problems(lab) == [
        "test-lab/meta.sample.tex: \\bbtVariant бэкенд не создаст — такого поля в template.yaml "
        "нет. Если шаблон его использует, у студента сборка упадёт",
        "test-lab/meta.sample.tex: нет \\bbtOption — бэкенд его создаст, а check-template без "
        "него собирает шаблон не так, как у студента",
    ]


CITY = "\\def\\bbtCity{Москва}\n"
NO_CITY = (
    "test-lab/meta.sample.tex: нет \\bbtCity — бэкенд его создаст, а check-template без него "
    "собирает шаблон не так, как у студента"
)


def bad_line(number: int) -> str:
    return (
        f"test-lab/meta.sample.tex: строка {number}: в meta.tex бэкенд пишет только "
        "\\def\\bbt…{…} — остального у студента не будет"
    )


@pytest.mark.parametrize(
    ("new", "expected"),
    [
        # Пакет из meta.sample.tex check-template подключил бы, а у студента его нет.
        (CITY + "\\usepackage{xcolor}\n", [bad_line(13)]),
        (CITY + "\\def\\bbtCity{Тверь}\n", ["test-lab/meta.sample.tex: \\bbtCity задан дважды"]),
        ("\\newcommand{\\bbtCity}{Москва}\n", [bad_line(12), NO_CITY]),
        # Незакрытая скобка не прячет макросы на следующих строках.
        ("\\def\\bbtCity{Москва\n", [bad_line(12), NO_CITY]),
    ],
    ids=["other command", "repeated", "newcommand", "unclosed brace"],
)
def test_sample_meta_format(lab: Path, new: str, expected: list[str]) -> None:
    replace_in(lab / "meta.sample.tex", CITY, new)

    assert problems(lab) == expected


def test_sample_meta_allows_comments_and_multiline_values(lab: Path) -> None:
    # Значение поля type: text бэкенд пишет в несколько строк; % внутри значения — \%.
    replace_in(
        lab / "meta.sample.tex",
        "\\def\\bbtLabTitle{Сортировки}\n",
        "\\def\\bbtLabTitle{Сортировки:\n\nвставками и {слиянием} на 100\\%} % тема\n\n",
    )

    assert problems(lab) == []


def test_sample_meta_missing(lab: Path) -> None:
    (lab / "meta.sample.tex").unlink()

    assert problems(lab) == [
        "test-lab/meta.sample.tex: нет файла — без него check-template не соберёт шаблон"
    ]


def test_backend_macros_follow_fields() -> None:
    templates = load_templates(TEMPLATE_FIXTURES)

    assert backend_macros(templates["test-lab"].manifest)[-3:] == [
        "LabNumber",
        "LabTitle",
        "Variant",
    ]
    # Поле discipline даёт не второй макрос, а \bbtDiscipline.
    any_lab = backend_macros(templates["test-any-lab"].manifest)
    assert any_lab.count("Discipline") == 1


def test_sample_meta_problems_without_file_text() -> None:
    manifest = load_templates(TEMPLATE_FIXTURES)["test-lab"].manifest

    assert sample_meta_problems("x/meta.sample.tex", manifest, "") == [
        f"x/meta.sample.tex: нет \\bbt{name} — бэкенд его создаст, а check-template без него "
        "собирает шаблон не так, как у студента"
        for name in sorted(backend_macros(manifest))
    ]
