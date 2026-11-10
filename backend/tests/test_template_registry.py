"""Реестр шаблонов: загрузка папки templates/ и ошибки, понятные автору шаблона."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.config import TEMPLATES_DIR, Settings
from app.main import create_app
from app.modules.templates.registry import TemplateError, load_templates
from tests.helpers import TEMPLATE_FIXTURES, TEST_TEMPLATES

# Меняет файлы скопированного шаблона-фикстуры test-lab.
Breaker = Callable[[Path], None]


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Копия шаблонов-фикстур, которую тест может портить."""
    target = tmp_path / "templates"
    shutil.copytree(TEMPLATE_FIXTURES, target)
    return target


def replace_in(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def problems(templates_dir: Path) -> str:
    with pytest.raises(TemplateError) as caught:
        load_templates(templates_dir)
    return str(caught.value)


def test_fixtures_load_with_files_to_copy() -> None:
    templates = load_templates(TEMPLATE_FIXTURES)

    assert list(templates) == sorted(TEST_TEMPLATES)
    lab = templates["test-lab"]
    assert lab.manifest.title == "Тестовая лабораторная"
    # template.yaml и meta.sample.tex в проект не копируются.
    assert sorted(lab.files) == ["main.tex", "sections/conclusion.tex", "sections/goal.tex"]
    assert lab.files["sections/goal.tex"] == "\\section{Цель работы}\n% Цель — из методички.\n"
    assert sorted(templates["test-vkr"].files) == ["chapters/intro.tex", "thesis.tex"]


def test_repository_templates_are_valid() -> None:
    # Проверка настоящих шаблонов в CI: сломанный template.yaml не попадёт в develop.
    load_templates(TEMPLATES_DIR)


def test_empty_folder_and_service_folders_give_empty_registry(tmp_path: Path) -> None:
    (tmp_path / "_shared").mkdir()
    (tmp_path / "_shared" / "mtuci-report.cls").write_text("% класс", encoding="utf-8")
    (tmp_path / ".vscode").mkdir()
    (tmp_path / "README.md").write_text("Шаблоны", encoding="utf-8")

    assert load_templates(tmp_path) == {}


@pytest.mark.parametrize(
    "junk", [".DS_Store", "figures/Thumbs.db", "figures/desktop.ini", "sections/.gitkeep"]
)
def test_os_and_hidden_files_are_skipped(templates_dir: Path, junk: str) -> None:
    # Их нет в git, но у разработчика они бывают — бэкенд из-за них не должен падать.
    path = templates_dir / "test-lab" / junk
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00junk")

    files = load_templates(templates_dir)["test-lab"].files

    assert sorted(files) == ["main.tex", "sections/conclusion.tex", "sections/goal.tex"]


def test_link_outside_template_is_error(templates_dir: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.tex"
    secret.write_text("SECRET", encoding="utf-8")
    try:
        (templates_dir / "test-lab" / "sections" / "leak.tex").symlink_to(secret)
    except OSError:
        pytest.skip("нет прав создавать ссылки (Windows без режима разработчика)")

    assert "test-lab/sections/leak.tex: ссылка ведёт за пределы папки шаблона" in problems(
        templates_dir
    )


def test_missing_folder_is_error(tmp_path: Path) -> None:
    assert f"Нет папки шаблонов {tmp_path / 'nope'}" in problems(tmp_path / "nope")


def test_windows_line_endings_are_normalized(templates_dir: Path) -> None:
    (templates_dir / "test-lab" / "main.tex").write_bytes(b"\\documentclass{article}\r\n")

    files = load_templates(templates_dir)["test-lab"].files

    assert files["main.tex"] == "\\documentclass{article}\n"


def _write(relative: str, data: bytes) -> Breaker:
    def breaker(lab: Path) -> None:
        (lab / relative).parent.mkdir(parents=True, exist_ok=True)
        (lab / relative).write_bytes(data)

    return breaker


def _replace(old: str, new: str) -> Breaker:
    return lambda lab: replace_in(lab / "template.yaml", old, new)


@pytest.mark.parametrize(
    ("breaker", "problem"),
    [
        (
            _replace("version: 1", "version: 1\n- item"),
            "test-lab/template.yaml: строка 5: expected <block end>",
        ),
        (
            _replace("version: 1", "version: 1\nversion: 2"),
            "test-lab/template.yaml: строка 5: ключ version повторяется",
        ),
        (
            _replace("version: 1", "version: 1\n? [a, b]\n: 1"),
            "test-lab/template.yaml: строка 5: found unhashable key",
        ),
        (
            _write("template.yaml", b"!!map scalar\n"),
            "test-lab/template.yaml: строка 1: expected a mapping node",
        ),
        (
            _replace("type: int", "type: number"),
            "test-lab/template.yaml: fields.0.type: Input should be",
        ),
        (
            _replace("key: variant", "key: group"),
            "test-lab/template.yaml: fields.2.key: ключ даёт макрос \\bbtGroup из 9.6 — он занят",
        ),
        (
            # В test-lab дисциплина уже есть в манифесте.
            _replace("key: variant", "key: discipline"),
            "test-lab/template.yaml: дисциплина задана и в шаблоне, и полем discipline",
        ),
        (
            _replace("slug: test-lab", "slug: other-lab"),
            "test-lab/template.yaml: slug: other-lab не совпадает с именем папки",
        ),
        (
            lambda lab: (lab / "main.tex").unlink(),
            "test-lab/template.yaml: main: нет файла main.tex",
        ),
        (
            lambda lab: (lab / "sections" / "conclusion.tex").unlink(),
            "test-lab/template.yaml: sections.1.file: нет файла sections/conclusion.tex",
        ),
        (
            _write("meta.tex", b"\\def\\bbtGroup{X}\n"),
            "test-lab/meta.tex: meta.tex создаёт бэкенд из профиля и полей (9.6)",
        ),
        (
            _write("figures/logo.png", b"\x89PNG"),
            "test-lab/figures/logo.png: шаблон может содержать только текстовые файлы",
        ),
        (
            _write("sections/цель#1.tex", b"x"),
            "test-lab/sections/цель#1.tex: Символ # в имени ломает сборку LaTeX",
        ),
        (
            _write("out/main.tex", b"x"),
            "test-lab/out/main.tex: папка out/ занята",
        ),
        (
            _write("sections/goal.tex", "Цель".encode("cp1251")),
            "test-lab/sections/goal.tex: файл не в кодировке UTF-8",
        ),
        (
            _write("sections/goal.tex", b"x" * (2 * 1024 * 1024 + 1)),
            "test-lab/sections/goal.tex: текстовый файл больше 2 МБ",
        ),
        (
            _write("template.yaml", b""),
            "test-lab/template.yaml: Input should be a valid dictionary",
        ),
        (
            lambda lab: (lab / "template.yaml").unlink(),
            "test-lab: нет файла template.yaml",
        ),
    ],
    ids=[
        "yaml syntax",
        "repeated key",
        "list as key",
        "scalar as map",
        "schema",
        "reserved key",
        "discipline twice",
        "slug",
        "main",
        "section file",
        "meta.tex",
        "binary",
        "tex special char",
        "out dir",
        "not utf-8",
        "too large",
        "empty manifest",
        "no manifest",
    ],
)
def test_problem_names_file_and_field(templates_dir: Path, breaker: Breaker, problem: str) -> None:
    breaker(templates_dir / "test-lab")

    assert problem in problems(templates_dir)


def test_all_problems_are_reported_at_once(templates_dir: Path) -> None:
    replace_in(templates_dir / "test-lab" / "template.yaml", "kind: lab", "kind: essay")
    replace_in(templates_dir / "test-vkr" / "template.yaml", "engine: pdflatex", "engine: lualatex")

    text = problems(templates_dir)

    assert "test-lab/template.yaml: kind: " in text
    assert "test-vkr/template.yaml: engine: " in text


def test_app_does_not_start_with_broken_template(templates_dir: Path) -> None:
    (templates_dir / "test-lab" / "main.tex").unlink()
    settings = Settings(_env_file=None, app_env="test", templates_dir=templates_dir)

    with pytest.raises(TemplateError) as caught:
        create_app(settings)

    assert "test-lab/template.yaml: main: нет файла main.tex" in str(caught.value)


def test_app_keeps_loaded_templates(settings: Settings) -> None:
    app = create_app(settings)

    assert sorted(app.state.templates) == sorted(TEST_TEMPLATES)
