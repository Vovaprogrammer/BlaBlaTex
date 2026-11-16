"""check-template без TeX: разбор лога и проверка папки шаблона."""

from pathlib import Path, PurePosixPath

import pytest

from app import check_template
from app.check_template import (
    Target,
    TexError,
    find_errors,
    github_annotations,
    main,
    read_target,
    repo_path,
    unwrap,
)

LOG = r"""This is XeTeX, Version 3.141592653-2.6-0.999997 (TeX Live 2025)
(./main.tex
LaTeX2e <2025-11-01>
./main.tex:5: Undefined control sequence.
l.5 \bbtNoSuchMacro
! Emergency stop.
Output written on out/main.xdv (1 page, 2304 bytes).
"""

# Ошибка LaTeX: строка исходника идёт не сразу, а после подсказки.
LATEX_ERROR_LOG = r"""./sections/progress.tex:12: LaTeX Error: Environment bbtcod undefined.

See the LaTeX manual or LaTeX Companion for explanation.
Type  H <return>  for immediate help.
 ...

l.12 \begin{bbtcod}
                   {python}{Сортировка}{lst:sort}
/opt/blablatex/tex/mtuci-report.cls:40: Missing number, treated as zero.
l.40 \setlength{\bbt@gap}{x}
"""

MTUCI_LAB = PurePosixPath("templates/mtuci-lab")


def test_find_errors_keeps_file_line_bang_and_source_lines() -> None:
    assert find_errors(LOG) == [
        TexError("Undefined control sequence.", "./main.tex", 5, r"l.5 \bbtNoSuchMacro"),
        TexError("! Emergency stop."),
    ]


def test_find_errors_takes_first_source_line_after_error() -> None:
    assert find_errors(LATEX_ERROR_LOG) == [
        TexError(
            "LaTeX Error: Environment bbtcod undefined.",
            "./sections/progress.tex",
            12,
            r"l.12 \begin{bbtcod}",
        ),
        TexError(
            "Missing number, treated as zero.",
            "/opt/blablatex/tex/mtuci-report.cls",
            40,
            r"l.40 \setlength{\bbt@gap}{x}",
        ),
    ]


def test_find_errors_with_spaces_in_file_name() -> None:
    line = "./sections/ход работы.tex:3: Undefined control sequence."

    assert find_errors(f"(./main.tex\n{line}\n") == [
        TexError("Undefined control sequence.", "./sections/ход работы.tex", 3)
    ]


@pytest.mark.parametrize(
    ("file", "path"),
    [
        ("./sections/goal.tex", "templates/mtuci-lab/sections/goal.tex"),
        ("main.tex", "templates/mtuci-lab/main.tex"),
        # meta.tex в сборке — копия meta.sample.tex.
        ("./meta.tex", "templates/mtuci-lab/meta.sample.tex"),
        ("/opt/blablatex/tex/mtuci-report.cls", "templates/_shared/mtuci-report.cls"),
        ("/usr/local/texlive/2025/texmf-dist/tex/latex/base/article.cls", None),
        # Файлы сборки — не файлы репозитория.
        ("./out/main.aux", None),
        ("out/main.toc", None),
    ],
)
def test_repo_path(file: str, path: str | None) -> None:
    assert repo_path(MTUCI_LAB, file) == path


def test_unwrap_joins_lines_wrapped_by_tex() -> None:
    line = "./sections/progress.tex:12: Package listings Error: Couldn't load requested language."
    wrapped = (line[:79] + "\n" + line[79:] + "\nl.12 \\end{bbtcode}\n").encode()

    assert unwrap(wrapped, "xelatex").splitlines()[:2] == [line, "l.12 \\end{bbtcode}"]


def test_unwrap_counts_bytes_for_pdflatex() -> None:
    # pdfTeX переносит по байтам: русская буква может разорваться посередине.
    line = ("./ход.tex:3: " + "ы" * 40).encode()
    wrapped = line[:79] + b"\n" + line[79:] + b"\n"

    assert unwrap(wrapped, "pdflatex").splitlines() == [line.decode()]


def test_annotation_on_file_line_with_source() -> None:
    errors = [
        TexError("Undefined control sequence.", "./sections/goal.tex", 5, r"l.5 \bbtLabGoal"),
        TexError("! Emergency stop."),
    ]

    assert github_annotations(MTUCI_LAB, errors, []) == [
        "::error file=templates/mtuci-lab/sections/goal.tex,line=5,"
        r"title=templates/mtuci-lab не собирается::Undefined control sequence.%0Al.5 \bbtLabGoal"
    ]


@pytest.mark.parametrize(
    "file", ["/usr/local/texlive/x.sty", "./out/main.aux"], ids=["tex live", "out"]
)
def test_annotation_without_file_shows_all_lines(file: str) -> None:
    # На строку файла репозитория указать нельзя — одна общая пометка.
    errors = [TexError("Missing number.", file, 3)]
    lines = [f"{file}:3: Missing number.", "100% done, a,b: c"]

    assert github_annotations(PurePosixPath("templates/x"), errors, lines) == [
        f"::error title=templates/x не собирается::{file}:3: Missing number.%0A100%25 done, a,b: c"
    ]


def test_annotation_title_escapes_property_characters() -> None:
    errors = [TexError("Oops.", "./c:d.tex", 1)]

    [annotation] = github_annotations(PurePosixPath("templates/a,b"), errors, [])

    assert annotation.startswith("::error file=templates/a%2Cb/c%3Ad.tex,line=1,")
    assert "title=templates/a%2Cb не собирается::Oops." in annotation


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
        ("main: main.tex\n", "нет ключа engine"),
        ("main: -e.tex\nengine: xelatex\n", "main: -e.tex — нужен относительный путь"),
        ("main: ../main.tex\nengine: xelatex\n", "main: ../main.tex — нужен относительный путь"),
        ("main: '`id`.tex'\nengine: xelatex\n", "main: `id`.tex — нужен относительный путь"),
        ("main: main.pdf\nengine: xelatex\n", "main: main.pdf — нужен относительный путь"),
        ("engine: xelatex\n", "нет ключа main"),
        ("main: null\nengine: xelatex\n", "main: None — нужен относительный путь"),
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
        "null main",
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


def test_several_templates_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Ошибка в первой папке не мешает проверить остальные; итог — в конце.
    (tmp_path / "a").mkdir()
    lualatex = write_template(tmp_path / "a", "main: main.tex\nengine: lualatex\n", "main.tex")
    missing = tmp_path / "nope"

    assert main([str(lualatex), str(missing)]) == 1
    output = capsys.readouterr().out
    assert "engine: lualatex" in output
    assert f"нет папки шаблона {missing}" in output
    assert output.rstrip().endswith(f"Собрано 0 из 2. С ошибками: {lualatex}, {missing}")


def test_problem_before_build_is_annotated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template = write_template(tmp_path, "main: main.tex\nengine: lualatex\n", "main.tex")

    assert main(["--github", str(template)]) == 1
    annotation = capsys.readouterr().out.splitlines()[-1]
    assert annotation.startswith("::error title=")
    assert "engine%3A lualatex" not in annotation  # двоеточие экранируется только в свойствах
    assert "engine: lualatex — собираются только xelatex" in annotation


def test_raw_log_lines_cannot_run_workflow_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Строки лога пишет шаблон (\typeout): с --github они печатаются внутри stop-commands.
    template = write_template(tmp_path, None, "main.tex")
    log = "::warning file=README.md::всё хорошо\nend of log\n"
    monkeypatch.setattr(check_template, "_build", lambda *_: (False, "status=timeout", log))

    assert main(["--github", str(template)]) == 1
    lines = capsys.readouterr().out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("::stop-commands::"))
    token = lines[start].removeprefix("::stop-commands::")
    assert len(token) == 32
    assert lines[start + 1 : start + 4] == [
        "::warning file=README.md::всё хорошо",
        "end of log",
        f"::{token}::",
    ]
    assert lines[start + 4].startswith("::error title=")


def test_copy_problem_does_not_stop_other_templates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(template: Path, dest: Path) -> None:
        raise PermissionError(13, "Permission denied", str(template / "main.tex"))

    first, second = tmp_path / "a", tmp_path / "b"
    for folder in (first, second):
        folder.mkdir()
        write_template(folder, None, "main.tex")
    monkeypatch.setattr(check_template, "_copy_template", unreadable)

    assert main([str(first), str(second)]) == 1
    output = capsys.readouterr().out
    assert output.count("Permission denied") == 2
    assert output.rstrip().endswith(f"Собрано 0 из 2. С ошибками: {first}, {second}")
