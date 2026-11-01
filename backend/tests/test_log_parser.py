"""Парсер лога TeX на настоящих логах компилятора (tests/fixtures/logs).

Логи получены у компилятора из docker compose на выдуманных документах ниже —
без данных студентов. Исходники лежат здесь же: по ним проверяется контекст ошибки.
"""

from pathlib import Path

import pytest

from app.modules.builds.log_parser import (
    MAX_ENTRIES,
    MAX_PRINT_LINE,
    ParsedLog,
    parse_log,
    unwrap,
)
from app.modules.builds.schemas import BuildError
from app.modules.projects.schemas import Engine

LOGS = Path(__file__).parent / "fixtures" / "logs"

PREAMBLE = (
    "\\documentclass{article}\n"
    "\\usepackage{fontspec}\n"
    "\\setmainfont{Liberation Serif}\n"
    "\\usepackage[russian]{babel}\n"
)
LONG_PATH = (
    "sections/a very long folder name for wrapping/and an even longer file name inside it.tex"
)

# Документы, из которых собраны логи: имя лога → файлы проекта.
SOURCES: dict[str, dict[str, str]] = {
    "ok_multipage": {
        "main.tex": PREAMBLE + "\\begin{document}\n\\input{sections/intro}\n\\newpage\n"
        "Вторая страница.\n\\newpage\nТретья страница.\n\\end{document}\n",
        "sections/intro.tex": "\\section{Введение}\nПервая страница.\n",
    },
    "undefined_cs_main": {
        "main.tex": PREAMBLE
        + "\\begin{document}\nЦель работы.\n\n\\textbff{Задание}\nТекст.\n\\end{document}\n"
    },
    "error_in_section": {
        "main.tex": PREAMBLE + "\\begin{document}\n\\input{sections/intro}\n"
        "\\input{sections/progress}\n\\end{document}\n",
        "sections/intro.tex": "\\section{Введение}\nВсё хорошо.\n",
        "sections/progress.tex": (
            "\\section{Ход работы}\nШаг первый.\n\\undefinedstep\nШаг второй.\n"
        ),
    },
    "missing_package": {
        "main.tex": PREAMBLE
        + "\\usepackage{nonexistentpkg}\n\\begin{document}\nТекст.\n\\end{document}\n"
    },
    "missing_input": {
        "main.tex": PREAMBLE + "\\begin{document}\n\\input{chapters/missing}\n\\end{document}\n"
    },
    "environment_mismatch": {
        "main.tex": PREAMBLE + "\\begin{document}\n\\begin{itemize}\n\\item Первый пункт\n"
        "\\item Второй пункт\n\\end{document}\n"
    },
    "missing_dollar": {
        "main.tex": PREAMBLE
        + "\\begin{document}\nПеременная my_var хранит счётчик.\n\\end{document}\n"
    },
    "warnings_pdflatex": {
        "main.tex": "\\documentclass{article}\n\\begin{document}\n"
        "\\section{Intro}\\label{sec:intro}\n"
        "See section~\\ref{sec:missing} and \\cite{knuth1984}.\n\n"
        "\\hbox to 1cm{Too wide text in a narrow box}\n\\end{document}\n"
    },
    "long_lines": {
        "main.tex": PREAMBLE
        + f"\\begin{{document}}\n\\input{{{LONG_PATH[:-4]}}}\n\\end{{document}}\n",
        LONG_PATH: "Текст.\n"
        "\\averyveryverylongmacronamethatdoesnotexistanywhereinthisdocumentatallreally\n",
    },
    "timeout_loop": {
        "main.tex": PREAMBLE + "\\begin{document}\n\\def\\loop{\\loop}\\loop\n\\end{document}\n"
    },
}


def parse(name: str) -> tuple[list[BuildError], int | None]:
    engine: Engine = "pdflatex" if name.endswith("_pdflatex") else "xelatex"
    parsed = parse_log((LOGS / f"{name}.log").read_bytes(), SOURCES[name], engine)
    return parsed.errors, parsed.pages


def parse_xetex(log: bytes, sources: dict[str, str]) -> ParsedLog:
    """Синтетический лог; движок — XeTeX, как у шаблонов."""
    return parse_log(log, sources, "xelatex")


def short(errors: list[BuildError]) -> list[tuple[str | None, int | None, str, str]]:
    """Ошибки без контекста — для сравнения целиком."""
    return [(error.file, error.line, error.message, error.severity) for error in errors]


def test_every_fixture_has_its_sources() -> None:
    assert sorted(path.stem for path in LOGS.glob("*.log")) == sorted(SOURCES)


def test_successful_build_has_no_errors_and_counts_pages() -> None:
    assert parse("ok_multipage") == ([], 3)


def test_undefined_control_sequence_names_the_command() -> None:
    errors, _ = parse("undefined_cs_main")

    assert short(errors) == [
        ("main.tex", 8, "Undefined control sequence: \\textbff", "error"),
    ]


def test_context_is_ten_lines_around_with_numbers() -> None:
    [error], _ = parse("undefined_cs_main")

    assert error.context.splitlines() == [
        "   1 | \\documentclass{article}",
        "   2 | \\usepackage{fontspec}",
        "   3 | \\setmainfont{Liberation Serif}",
        "   4 | \\usepackage[russian]{babel}",
        "   5 | \\begin{document}",
        "   6 | Цель работы.",
        "   7 | ",
        ">  8 | \\textbff{Задание}",
        "   9 | Текст.",
        "  10 | \\end{document}",
    ]


def test_error_in_included_file_points_to_that_file() -> None:
    errors, _ = parse("error_in_section")

    assert short(errors) == [
        ("sections/progress.tex", 3, "Undefined control sequence: \\undefinedstep", "error"),
    ]
    # Номера выровнены по самому длинному: в файле 4 строки — ширина 1.
    assert "> 3 | \\undefinedstep" in errors[0].context.splitlines()


def test_missing_package_is_one_error_without_emergency_stop() -> None:
    errors, pages = parse("missing_package")

    assert short(errors) == [("main.tex", 6, "File `nonexistentpkg.sty' not found.", "error")]
    assert pages is None


def test_missing_input_file() -> None:
    errors, _ = parse("missing_input")

    assert short(errors) == [("main.tex", 6, "File `chapters/missing.tex' not found.", "error")]


def test_wrapped_error_message_is_joined() -> None:
    errors, _ = parse("environment_mismatch")

    assert short(errors)[0] == (
        "main.tex",
        9,
        "\\begin{itemize} on input line 6 ended by \\end{document}.",
        "error",
    )


def test_every_missing_dollar_is_reported() -> None:
    errors, _ = parse("missing_dollar")

    assert short(errors) == [
        ("main.tex", 6, "Missing $ inserted.", "error"),
        ("main.tex", 7, "Missing $ inserted.", "error"),
    ]


def test_latex_warnings_with_input_line() -> None:
    errors, pages = parse("warnings_pdflatex")

    # Overfull/Underfull — типографские мелочи, их не показываем.
    assert short(errors) == [
        ("main.tex", 4, "Reference `sec:missing' on page 1 undefined", "warning"),
        ("main.tex", 4, "Citation `knuth1984' on page 1 undefined", "warning"),
        (None, None, "There were undefined references", "warning"),
    ]
    assert pages == 1


def test_long_file_path_wrapped_by_tex_is_found() -> None:
    errors, _ = parse("long_lines")

    [error] = errors
    assert (error.file, error.line, error.severity) == (LONG_PATH, 2, "error")
    # Команда обрезана в логе («l.2 ...esnotexist…») — имени нет, остаётся текст TeX.
    assert error.message == "Undefined control sequence."
    assert "> 2 | \\averyvery" in error.context


def test_log_cut_by_timeout_has_no_errors() -> None:
    assert parse("timeout_loop") == ([], None)


# Синтетические строки — случаи, которых нет в логах выше.


def test_unwrap_joins_only_lines_of_exactly_79_chars() -> None:
    first = "x" * MAX_PRINT_LINE
    log = f"{first}\ntail\n{'y' * 78}\nnext".encode()

    assert unwrap(log, "xelatex") == [first + "tail", "y" * 78, "next"]


def test_unwrap_counts_bytes_for_pdftex_and_chars_for_xetex() -> None:
    # pdfTeX переносит по байтам — посреди русской буквы; XeTeX — по символам.
    word = "Ж".encode()
    pdftex = b"a" * (MAX_PRINT_LINE - 1) + word[:1] + b"\n" + word[1:] + b"b\n"
    xetex = ("Ж" * MAX_PRINT_LINE + "\nb\n").encode()

    assert unwrap(pdftex, "pdflatex")[0] == "a" * (MAX_PRINT_LINE - 1) + "Жb"
    assert unwrap(xetex, "xelatex")[0] == "Ж" * MAX_PRINT_LINE + "b"


def test_unwrap_does_not_join_complete_lines_of_the_other_measure() -> None:
    # 79 байт, но меньше 79 символов: XeTeX такую строку не переносил.
    xetex_line = "Ж" * 30 + "a" * (MAX_PRINT_LINE - 60)
    # 79 символов, но больше 79 байт: pdfTeX перенёс бы её раньше — значит, это целая строка.
    pdftex_line = "Ж" * MAX_PRINT_LINE

    assert unwrap(f"{xetex_line}\nl.12 \\foo".encode(), "xelatex") == [xetex_line, "l.12 \\foo"]
    assert unwrap(f"{pdftex_line}\nnext".encode(), "pdflatex") == [pdftex_line, "next"]


def test_crlf_line_endings_do_not_break_unwrapping() -> None:
    log = ("x" * MAX_PRINT_LINE + "\r\ntail\r\n").encode()

    assert unwrap(log, "xelatex")[0] == "x" * MAX_PRINT_LINE + "tail"


def test_package_warning_continuation_lines_and_current_file() -> None:
    log = b"\n".join(
        [
            b"(./main.tex (./sections/a.tex",
            b"Package hyperref Warning: Token not allowed in a PDF string,",
            b"(hyperref)                removing `math shift' on input line 3.",
            b"",
            b") (./sections/b.tex",
            b"LaTeX Warning: Reference `x' on page 2 undefined on input line 7.",
            b"))",
        ]
    )
    sources = {"main.tex": "", "sections/a.tex": "a\n" * 5, "sections/b.tex": "b\n" * 9}

    errors = parse_xetex(log, sources).errors

    assert short(errors) == [
        (
            "sections/a.tex",
            3,
            "Token not allowed in a PDF string, removing `math shift'",
            "warning",
        ),
        ("sections/b.tex", 7, "Reference `x' on page 2 undefined", "warning"),
    ]


def test_warning_while_package_file_is_open_is_not_put_on_project_file() -> None:
    # «input line 112» — строка внутри пакета, а не main.tex.
    log = b"\n".join(
        [
            b"(./main.tex (/usr/local/texlive/2025/texmf-dist/tex/generic/babel/babel.sty",
            b"Package babel Warning: Something odd on input line 112.",
            b"",
            b")",
            b"LaTeX Warning: Reference `x' on page 1 undefined on input line 3.",
            b")",
        ]
    )

    errors = parse_xetex(log, {"main.tex": "a\nb\nc\n"}).errors

    assert short(errors) == [
        (None, None, "Something odd", "warning"),
        ("main.tex", 3, "Reference `x' on page 1 undefined", "warning"),
    ]


def test_parentheses_in_document_text_do_not_break_file_tracking() -> None:
    # Скобки из текста студента: в контексте ошибки, в «<argument>» и в переполненном боксе.
    log = b"\n".join(
        [
            b"(./main.tex (./sections/a.tex",
            b"./sections/a.tex:2: Undefined control sequence.",
            b"l.2 ...)) \\foo",
            b"            (see figure",
            b"<argument> text) more)",
            b"               ",
            b"Overfull \\hbox (12.0pt too wide) in paragraph at lines 3--4",
            b"[]\\TU/LiberationSerif(0)/m/n/10 closing ) paren",
            b"",
            b"LaTeX Warning: Reference `x' on page 1 undefined on input line 4.",
            b"",
            b") (./sections/b.tex",
            b"LaTeX Warning: Reference `y' on page 1 undefined on input line 1.",
            b"))",
        ]
    )
    sources = {"main.tex": "", "sections/a.tex": "x\n" * 5, "sections/b.tex": "y\n"}

    errors = parse_xetex(log, sources).errors

    assert [(error.file, error.line) for error in errors] == [
        ("sections/a.tex", 2),
        ("sections/a.tex", 4),
        ("sections/b.tex", 1),
    ]


def test_file_names_with_spaces_and_prefixes_are_told_apart() -> None:
    log = b"(./main.tex (./a b.tex (./a.tex\nLaTeX Warning: W on input line 1.\n\n)))"
    sources = {"main.tex": "", "a b.tex": "1\n", "a.tex": "1\n", "a b.tex.bak": ""}

    [error] = parse_xetex(log, sources).errors

    assert error.file == "a.tex"


def test_many_parentheses_are_parsed_quickly() -> None:
    # Зациклившийся \message{(} даёт мегабайты скобок; разбор не перебирает файлы на каждую.
    sources = {f"sections/part{n}.tex": "" for n in range(500)}
    log = b"(" * 1_000_000 + b"\n./sections/part7.tex:1: Undefined control sequence.\n"

    errors = parse_xetex(log, sources).errors

    assert short(errors) == [("sections/part7.tex", 1, "Undefined control sequence.", "error")]


def test_context_counts_lines_like_tex() -> None:
    # Перевод страницы и разделитель строк Unicode — не концы строк для TeX.
    source = "a\fb\nc d\r\nerror here\rlast\n"
    log = b"./main.tex:3: Undefined control sequence.\n"

    [error] = parse_xetex(log, {"main.tex": source}).errors

    assert error.context.split("\n")[2] == "> 3 | error here"
    assert error.context.count("|") == 4


def test_error_in_system_file_has_no_file_and_line() -> None:
    log = (
        b"(./main.tex (/opt/blablatex/tex/mtuci-report.cls\n"
        b"/opt/blablatex/tex/mtuci-report.cls:120: Bad thing.\n"
    )

    errors = parse_xetex(log, {"main.tex": ""}).errors

    assert short(errors) == [(None, None, "Bad thing.", "error")]


def test_text_that_only_looks_like_file_line_is_ignored() -> None:
    log = b"Chapter 1:2: not an error\n"

    assert parse_xetex(log, {"main.tex": ""}).errors == []


def test_line_outside_source_has_empty_context() -> None:
    log = b"./main.tex:99: Undefined control sequence.\nl.99 \\foo\n"

    [error] = parse_xetex(log, {"main.tex": "one line\n"}).errors

    assert (error.line, error.context) == (99, "")


@pytest.mark.parametrize("severity", ["error", "warning"])
def test_entries_are_limited(severity: str) -> None:
    template = (
        "./main.tex:{n}: Undefined control sequence.\n"
        if severity == "error"
        else "LaTeX Warning: Reference `r{n}' undefined on input line {n}.\n"
    )
    log = "".join(template.format(n=n) for n in range(1, 500)).encode()

    errors = parse_xetex(log, {"main.tex": ""}).errors

    assert len(errors) == MAX_ENTRIES


def test_errors_are_kept_before_warnings_when_limited() -> None:
    warnings = "".join(f"LaTeX Warning: W{n} on input line {n}.\n" for n in range(1, 60))
    log = (warnings + "./main.tex:1: Undefined control sequence.\n").encode()

    errors = parse_xetex(log, {"main.tex": "x\n"}).errors

    assert len(errors) == MAX_ENTRIES
    assert errors[-1].severity == "error"
    assert sum(error.severity == "warning" for error in errors) == MAX_ENTRIES - 1


def test_same_error_twice_is_reported_once() -> None:
    line = b"./main.tex:1: Undefined control sequence.\n"

    assert len(parse_xetex(line * 2, {"main.tex": "x\n"}).errors) == 1


def test_singular_page() -> None:
    log = b"Output written on out/main.pdf (1 page, 33265 bytes).\n"

    assert parse_xetex(log, {}).pages == 1
