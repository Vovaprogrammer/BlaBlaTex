"""Общие правила ProjectTools (architecture.md 9.4): нумерация строк, замена, поиск, коды ошибок.

Ими пользуются и фейк, и настоящая реализация — здесь правила проверяются один раз сами по себе.
"""

import pytest

from app.core.errors import ErrorCode
from app.modules.projects.tools import (
    SNIPPET_MAX_CHARS,
    ToolError,
    ToolErrorCode,
    check_image,
    check_search,
    count_occurrences,
    find_lines,
    material_slice,
    read_lines,
    replace_once,
    split_lines,
)

# Коды, которых нет в REST: у сервиса файлов нет таких ошибок.
TOOL_ONLY_CODES = {"invalid_path", "edit_not_found", "edit_not_unique", "material_not_ready"}


def test_codes_match_rest_where_error_is_the_same() -> None:
    shared = {code.value for code in ToolErrorCode} - TOOL_ONLY_CODES
    assert shared <= {code.value for code in ErrorCode}


def test_tool_error_keeps_code_message_and_details() -> None:
    error = ToolError(ToolErrorCode.EDIT_NOT_UNIQUE, "Фрагмент найден несколько раз", {"count": 2})
    assert (error.code, error.message, error.details) == (
        "edit_not_unique",
        "Фрагмент найден несколько раз",
        {"count": 2},
    )
    assert str(error) == "Фрагмент найден несколько раз"
    assert ToolError(ToolErrorCode.NOT_FOUND, "Нет").details == {}


@pytest.mark.parametrize(
    ("content", "lines"),
    [
        ("", []),
        ("a", ["a"]),
        ("a\n", ["a"]),
        ("\n", [""]),
        ("a\n\nb", ["a", "", "b"]),
        ("a\n\n", ["a", ""]),
        # Только \n: \r остаётся в строке, \f строку не делит.
        ("a\r\nb\fc", ["a\r", "b\fc"]),
    ],
)
def test_split_lines(content: str, lines: list[str]) -> None:
    assert split_lines(content) == lines


def test_read_lines_numbers_whole_file() -> None:
    text = read_lines("main.tex", 3, "\\section{Цель}\n\nТекст\n")
    assert text.text == "1\t\\section{Цель}\n2\t\n3\tТекст"
    assert (text.path, text.version, text.start_line, text.end_line, text.total_lines) == (
        "main.tex",
        3,
        1,
        3,
        3,
    )


def test_read_lines_range_is_inclusive_and_clipped() -> None:
    content = "one\ntwo\nthree\nfour"
    assert read_lines("a.tex", 1, content, 2, 3).text == "2\ttwo\n3\tthree"
    clipped = read_lines("a.tex", 1, content, 3, 100)
    assert (clipped.text, clipped.end_line) == ("3\tthree\n4\tfour", 4)
    assert read_lines("a.tex", 1, content, start_line=4).text == "4\tfour"
    assert read_lines("a.tex", 1, content, end_line=1).text == "1\tone"


def test_read_lines_beyond_end_is_empty() -> None:
    text = read_lines("a.tex", 1, "one\ntwo", start_line=5)
    assert (text.text, text.start_line, text.end_line, text.total_lines) == ("", 5, 2, 2)
    empty = read_lines("a.tex", 1, "")
    assert (empty.text, empty.start_line, empty.end_line, empty.total_lines) == ("", 1, 0, 0)


@pytest.mark.parametrize(("start", "end"), [(0, None), (-1, 2), (3, 2)])
def test_read_lines_rejects_bad_range(start: int, end: int | None) -> None:
    with pytest.raises(ToolError) as error:
        read_lines("a.tex", 1, "one\ntwo\nthree", start, end)
    assert error.value.code == ToolErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize(
    ("text", "fragment", "count"),
    [("abc", "d", 0), ("abc", "b", 1), ("abab", "ab", 2), ("aaa", "aa", 2), ("ааа", "аа", 2)],
)
def test_count_occurrences_with_overlaps(text: str, fragment: str, count: int) -> None:
    assert count_occurrences(text, fragment) == count


def test_replace_once_returns_text_and_line() -> None:
    content = "\\section{Цель}\nИзучить списки.\n\\section{Ход}\n"
    new, line = replace_once(content, "Изучить списки.", "Изучить списки и стеки.")
    assert new == "\\section{Цель}\nИзучить списки и стеки.\n\\section{Ход}\n"
    assert line == 2


def test_replace_once_multiline_fragment() -> None:
    new, line = replace_once("a\nb\nc\nd\n", "b\nc\n", "")
    assert (new, line) == ("a\nd\n", 2)


def test_replace_once_not_found() -> None:
    with pytest.raises(ToolError) as error:
        replace_once("abc", "x", "y")
    assert error.value.code == ToolErrorCode.EDIT_NOT_FOUND


@pytest.mark.parametrize(("content", "old", "count"), [("ab ab ab", "ab", 3), ("aaa", "aa", 2)])
def test_replace_once_not_unique_reports_count(content: str, old: str, count: int) -> None:
    with pytest.raises(ToolError) as error:
        replace_once(content, old, "x")
    assert error.value.code == ToolErrorCode.EDIT_NOT_UNIQUE
    assert error.value.details == {"count": count}
    assert str(count) in error.value.message


def test_replace_once_rejects_empty_fragment() -> None:
    with pytest.raises(ToolError) as error:
        replace_once("abc", "", "x")
    assert error.value.code == ToolErrorCode.VALIDATION_ERROR


def test_find_lines_ignores_case() -> None:
    hits = list(find_lines("sections/goal.tex", "Цель работы\nцель\nХод работы\n", "ЦЕЛЬ"))
    assert [(hit.path, hit.line, hit.snippet) for hit in hits] == [
        ("sections/goal.tex", 1, "Цель работы"),
        ("sections/goal.tex", 2, "цель"),
    ]
    assert list(find_lines("a.tex", "abc", "x")) == []


def test_find_lines_snippet_shows_match_in_long_line() -> None:
    line = "x" * 500 + "искомое" + "y" * 500
    (hit,) = find_lines("a.tex", line, "искомое")
    assert "искомое" in hit.snippet
    assert len(hit.snippet) == SNIPPET_MAX_CHARS
    (tail,) = find_lines("a.tex", "x" * 500 + "конец", "конец")
    assert tail.snippet.endswith("конец")
    assert len(tail.snippet) == SNIPPET_MAX_CHARS


@pytest.mark.parametrize(("query", "max_results"), [("", 10), ("a", 0), ("a", -1)])
def test_check_search_rejects_bad_arguments(query: str, max_results: int) -> None:
    with pytest.raises(ToolError) as error:
        check_search(query, max_results)
    assert error.value.code == ToolErrorCode.VALIDATION_ERROR


def test_material_slice() -> None:
    text = "Методичка: задание 1"
    first = material_slice(text, 0, 9)
    assert (first.text, first.offset, first.total) == ("Методичка", 0, 20)
    assert material_slice(text, 11, 100).text == "задание 1"
    assert material_slice(text, 100, 10).text == ""


@pytest.mark.parametrize(("offset", "limit"), [(-1, 10), (0, 0)])
def test_material_slice_rejects_bad_arguments(offset: int, limit: int) -> None:
    with pytest.raises(ToolError) as error:
        material_slice("abc", offset, limit)
    assert error.value.code == ToolErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize("path", ["materials/shot.png", "figures/a.JPG", "b.jpeg"])
def test_check_image_accepts_pictures(path: str) -> None:
    check_image(path)


@pytest.mark.parametrize("path", ["figures/scheme.svg", "main.tex", "materials/lab.pdf", "png"])
def test_check_image_rejects_other_files(path: str) -> None:
    with pytest.raises(ToolError) as error:
        check_image(path)
    assert error.value.code == ToolErrorCode.UNSUPPORTED_FILE_TYPE
