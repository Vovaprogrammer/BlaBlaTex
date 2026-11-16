"""check-template без TeX: разбор лога и проверка папки шаблона."""

from pathlib import Path

import pytest

from app.check_template import Target, find_errors, main, read_target

LOG = r"""This is XeTeX, Version 3.141592653-2.6-0.999997 (TeX Live 2025)
(./main.tex
LaTeX2e <2025-11-01>
./main.tex:5: Undefined control sequence.
l.5 \bbtNoSuchMacro
! Emergency stop.
Output written on out/main.xdv (1 page, 2304 bytes).
"""


def test_find_errors_keeps_file_line_and_bang_lines() -> None:
    assert find_errors(LOG) == ["./main.tex:5: Undefined control sequence.", "! Emergency stop."]


def test_find_errors_with_spaces_in_file_name() -> None:
    line = "./sections/ход работы.tex:3: Undefined control sequence."

    assert find_errors(f"(./main.tex\n{line}\n") == [line]


def test_template_must_not_have_out_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("main.tex", "meta.sample.tex", "out/main.pdf"):
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text("")

    assert main([str(tmp_path)]) == 1
    assert "папка out/" in capsys.readouterr().out


def test_missing_template_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "nope")]) == 1
    assert "нет папки шаблона" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["main.tex", "meta.sample.tex"])
def test_template_needs_main_and_sample_meta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    for name in {"main.tex", "meta.sample.tex"} - {missing}:
        (tmp_path / name).write_text("")

    assert main([str(tmp_path)]) == 1
    assert f"нет файла {missing}" in capsys.readouterr().out


def write_template(root: Path, manifest: str | None, *files: str) -> Path:
    """Папка шаблона: template.yaml (если задан), meta.sample.tex и пустые файлы files."""
    if manifest is not None:
        (root / "template.yaml").write_text(manifest, encoding="utf-8")
    for name in ("meta.sample.tex", *files):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("")
    return root


def test_without_manifest_builds_main_tex_with_xelatex(tmp_path: Path) -> None:
    assert read_target(write_template(tmp_path, None)) == Target("main.tex", "xelatex")


def test_main_and_engine_come_from_manifest(tmp_path: Path) -> None:
    # Остальные ключи манифеста проверяет бэкенд, здесь они не нужны.
    template = write_template(tmp_path, "slug: x\nmain: src/report.tex\nengine: pdflatex\n")

    assert read_target(template) == Target("src/report.tex", "pdflatex")


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        ("main: main.tex\nengine: lualatex\n", "engine: lualatex — собираются только xelatex"),
        ("main: main.tex\n", "engine: None — собираются только xelatex"),
        ("main: -e.tex\nengine: xelatex\n", "main: -e.tex — нужен относительный путь"),
        ("main: ../main.tex\nengine: xelatex\n", "main: ../main.tex — нужен относительный путь"),
        ("main: '`id`.tex'\nengine: xelatex\n", "main: `id`.tex — нужен относительный путь"),
        ("main: main.pdf\nengine: xelatex\n", "main: main.pdf — нужен относительный путь"),
        ("engine: xelatex\n", "main: None — нужен относительный путь"),
        ("- main.tex\n", "нужен словарь ключей"),
        ("main: [\n", "файл не читается"),
    ],
    ids=[
        "lualatex",
        "no engine",
        "option",
        "parent",
        "backquote",
        "not tex",
        "no main",
        "list",
        "yaml",
    ],
)
def test_wrong_main_or_engine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest: str, problem: str
) -> None:
    write_template(tmp_path, manifest, "main.tex")

    assert main([str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert f"ОШИБКА: {tmp_path / 'template.yaml'}: " in output
    assert problem in output


def test_main_from_manifest_must_exist(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_template(tmp_path, "main: report.tex\nengine: xelatex\n", "main.tex")

    assert main([str(tmp_path)]) == 1
    assert "нет файла report.tex" in capsys.readouterr().out
