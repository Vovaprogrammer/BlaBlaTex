"""Манифест template.yaml (architecture.md 9.5): что модель принимает и что отвергает."""

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.templates.manifest import TemplateManifest, macro_suffix

# Any — манифест как его отдаёт YAML: словари, списки, строки и числа.
Manifest = dict[str, Any]

# Пример из 9.5.
EXAMPLE: Manifest = {
    "slug": "mtuci-lab-siaod",
    "version": 1,
    "kind": "lab",
    "title": "Лабораторная работа — СиАОД",
    "discipline": "Структуры и алгоритмы обработки данных",
    "engine": "xelatex",
    "main": "main.tex",
    "fields": [
        {"key": "lab_number", "label": "Номер работы", "type": "int", "required": True},
        {"key": "lab_title", "label": "Тема работы", "type": "string", "required": True},
        {"key": "variant", "label": "Вариант", "type": "string"},
        {"key": "teacher", "label": "Преподаватель", "type": "string", "default": ""},
        {
            "key": "work_type",
            "label": "Вид работы",
            "type": "select",
            "options": ["Лабораторная работа", "Практическая работа"],
            "default": "Лабораторная работа",
        },
    ],
    "sections": [
        {
            "id": "goal",
            "title": "Цель работы",
            "file": "sections/goal.tex",
            "required": True,
            "guide": "1–2 предложения.",
        },
        {"id": "conclusion", "title": "Выводы", "file": "sections/conclusion.tex"},
    ],
    "ai_rules": "Общие правила для ИИ в этом шаблоне.\n",
    "checks": [],
}


def errors(manifest: Manifest) -> list[tuple[tuple[str | int, ...], str]]:
    """Ошибки проверки манифеста: (где, текст)."""
    with pytest.raises(ValidationError) as caught:
        TemplateManifest.model_validate(manifest)
    return [(error["loc"], error["msg"]) for error in caught.value.errors()]


def changed(path: tuple[str | int, ...], value: Any) -> Manifest:  # Any — значение из YAML
    """Пример из 9.5, в котором значение по пути path заменено на value."""
    manifest = copy.deepcopy(EXAMPLE)
    target = manifest
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return manifest


def test_example_from_architecture_is_valid() -> None:
    manifest = TemplateManifest.model_validate(EXAMPLE)

    assert manifest.slug == "mtuci-lab-siaod"
    assert [field.key for field in manifest.fields] == [
        "lab_number", "lab_title", "variant", "teacher", "work_type",
    ]  # fmt: skip
    assert manifest.fields[2].required is False
    assert manifest.fields[2].default is None
    assert manifest.fields[2].options == []
    assert manifest.sections[1].guide == ""


def test_optional_keys_have_defaults() -> None:
    required = {key: EXAMPLE[key] for key in ("slug", "version", "kind", "title", "engine", "main")}

    manifest = TemplateManifest.model_validate(required)

    assert (manifest.discipline, manifest.fields, manifest.sections) == (None, [], [])
    assert (manifest.ai_rules, manifest.checks) == ("", [])


@pytest.mark.parametrize("key", ["slug", "version", "kind", "title", "engine", "main"])
def test_required_keys(key: str) -> None:
    manifest = {k: v for k, v in EXAMPLE.items() if k != key}

    assert [loc for loc, _ in errors(manifest)] == [(key,)]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("checkz",), []),
        (("fields", 0, "lable"), "Номер"),
        (("sections", 0, "guidе"), "Кириллическая «е» в ключе"),
    ],
    ids=["manifest", "field", "section"],
)
def test_unknown_key_is_error(path: tuple[str | int, ...], value: Any) -> None:  # Any — из YAML
    assert errors(changed(path, value)) == [(path, "Extra inputs are not permitted")]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("version",), "1"),
        (("version",), 0),
        (("kind",), "report"),
        (("engine",), "lualatex"),
        (("slug",), "Mtuci_Lab"),
        (("title",), ""),
        (("fields", 0, "required"), "yes"),
        (("fields", 0, "type"), "number"),
        (("fields", 3, "default"), True),
    ],
)
def test_wrong_value_is_error(path: tuple[str | int, ...], value: Any) -> None:  # Any — из YAML
    # У default — по ошибке на каждый тип из str | int, у них в конце loc ещё имя типа.
    assert {loc[: len(path)] for loc, _ in errors(changed(path, value))} == {path}


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("lab2", "should match pattern"),
        ("Lab", "should match pattern"),
        ("lab__number", "should match pattern"),
        ("group", "\\bbtGroup из 9.6 — он занят"),
        ("last_name", "\\bbtLastName из 9.6 — он занят"),
        ("title_page", "\\bbtTitlePage из 9.6 — он занят"),
    ],
)
def test_field_key_must_give_free_macro_name(key: str, message: str) -> None:
    [(loc, text)] = errors(changed(("fields", 0, "key"), key))

    assert loc == ("fields", 0, "key")
    assert message in text


@pytest.mark.parametrize(
    ("field", "loc", "message"),
    [
        ({"type": "select"}, "options", "нужен непустой список options"),
        ({"type": "select", "options": []}, "options", "нужен непустой список options"),
        (
            {"type": "string", "options": ["А"]},
            "options",
            "options бывают только у поля type: select",
        ),
        ({"type": "select", "options": ["А", "А"]}, "options", "варианты в options повторяются"),
        ({"type": "select", "options": ["А"], "default": "Б"}, "default", "одним из options"),
        ({"type": "int", "default": "3"}, "default", "default должен быть числом"),
        ({"type": "text", "default": 3}, "default", "default должен быть строкой"),
    ],
)
def test_options_and_default_match_type(field: dict[str, Any], loc: str, message: str) -> None:
    [(where, text)] = errors(changed(("fields", 0), {"key": "x", "label": "Икс"} | field))

    assert where == ("fields", 0, loc)
    assert message in text


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("fields", 1, "key"), "lab_number", "ключ поля lab_number повторяется"),
        (("sections", 1, "id"), "goal", "id раздела goal повторяется"),
        (
            ("sections", 1, "file"),
            "sections/goal.tex",
            "файл раздела sections/goal.tex повторяется",
        ),
    ],
)
def test_repeats_are_errors(path: tuple[str | int, ...], value: str, message: str) -> None:
    [(loc, text)] = errors(changed(path, value))

    assert loc == path[:1]
    assert message in text


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("sections", 0, "file"), "../goal.tex"),
        (("sections", 0, "file"), "sections/goal.txt"),
        (("sections", 0, "file"), "sections/цель#1.tex"),
        (("main",), "главный.tex"),
        (("main",), "-main.tex"),
        (("main",), "out/../main.tex"),
    ],
)
def test_files_follow_path_rules(path: tuple[str | int, ...], value: str) -> None:
    assert [loc for loc, _ in errors(changed(path, value))] == [path]


@pytest.mark.parametrize(
    ("key", "suffix"),
    [("lab_number", "LabNumber"), ("variant", "Variant"), ("a_b_c", "ABC")],
)
def test_macro_suffix_is_camel_case(key: str, suffix: str) -> None:
    assert macro_suffix(key) == suffix
