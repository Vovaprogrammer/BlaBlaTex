"""SyncTeX с настоящей программой synctex: строка ↔ место в PDF на собранном документе."""

import base64
from typing import Any

import pytest

from tests.support import Compiler

# Как отчёт по шаблону: титульный лист из макроса класса, раздел в папке с русским именем,
# код из материалов и картинка. \titul стоит на строке 5 — на ней титульный лист уходит в
# печать, как у \bbtTitlePage.
MAIN_TEX = r"""\documentclass{bbt-test}
\usepackage{graphicx}
\newcommand\titul{\begin{center}Титульный лист\\Иванов И. И.\end{center}\newpage}
\begin{document}
\titul
\input{разделы/цель}
\lstinputlisting{materials/lab.py}
\includegraphics[width=3cm]{materials/pixel.png}
\end{document}
"""
TITLE_LINE, LISTING_LINE, PICTURE_LINE, END_LINE = 5, 7, 8, 9
GOAL_TEX = """Изучить методы поиска в массиве и сравнить их.

% комментарий студента
Сравнить линейный и бинарный поиск по числу сравнений.

Сделать выводы о том, какой поиск быстрее на отсортированном массиве.
"""
LAB_PY = """def linear(a, x):
    for i, v in enumerate(a):
        if v == x:
            return i
    return -1
"""
GOAL = "разделы/цель.tex"
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# Any: ответы — JSON с числами, строками и null.
Json = dict[str, Any]


@pytest.fixture(scope="module")
def synctex(compiler: Compiler) -> bytes:
    build = compiler.compile(
        {
            "main.tex": MAIN_TEX,
            GOAL: GOAL_TEX,
            "materials/lab.py": LAB_PY,
            "materials/pixel.png": PIXEL_PNG,
        }
    )
    assert build.result["status"] == "ok", build.log
    return build.files["output.synctex.gz"]


def view(compiler: Compiler, synctex: bytes, path: str, line: int) -> list[Json]:
    response = compiler.synctex("view", synctex, path=path, line=line)
    assert response.status_code == 200, response.text
    boxes: list[Json] = response.json()["boxes"]
    return boxes


def edit(compiler: Compiler, synctex: bytes, page: int, x: float, y: float) -> Json | None:
    response = compiler.synctex("edit", synctex, page=page, x=x, y=y)
    assert response.status_code == 200, response.text
    source: Json | None = response.json()["source"]
    return source


@pytest.mark.parametrize("line", [1, 4, 6])
def test_line_to_pdf_and_back(compiler: Compiler, synctex: bytes, line: int) -> None:
    [box, *_] = view(compiler, synctex, GOAL, line)

    assert box["page"] == 2
    assert box["width"] > 100 and 5 < box["height"] < 30
    # Клик у начала строки, на высоте её текста.
    source = edit(compiler, synctex, 2, box["x"] + 20, box["y"] + box["height"] / 2)
    assert source is not None
    assert source["path"] == GOAL
    assert abs(source["line"] - line) <= 1


def test_comment_and_empty_line_show_nearest_text(compiler: Compiler, synctex: bytes) -> None:
    text = view(compiler, synctex, GOAL, 4)

    assert view(compiler, synctex, GOAL, 3)
    assert view(compiler, synctex, GOAL, 5)
    assert view(compiler, synctex, GOAL, 3)[0]["y"] <= text[0]["y"]


def test_code_from_materials(compiler: Compiler, synctex: bytes) -> None:
    boxes = view(compiler, synctex, "materials/lab.py", 3)
    [box, *_] = boxes

    assert all(item["x"] >= 0 for item in boxes)
    middle = box["y"] + box["height"] / 2
    # Клик по самому коду — строка кода; по пустому месту строки листинга — строка с
    # \lstinputlisting, где код подключён.
    sources = {
        (source["path"], source["line"])
        for x in range(int(box["x"]), int(box["x"] + box["width"]), 5)
        if (source := edit(compiler, synctex, box["page"], x, middle)) is not None
    }
    assert ("materials/lab.py", 3) in sources
    assert sources <= {
        ("materials/lab.py", 2),
        ("materials/lab.py", 3),
        ("main.tex", LISTING_LINE),
    }


def test_picture_points_to_its_line(compiler: Compiler, synctex: bytes) -> None:
    boxes = view(compiler, synctex, "main.tex", PICTURE_LINE)

    [picture] = [box for box in boxes if box["height"] > 50]
    assert edit(
        compiler,
        synctex,
        picture["page"],
        picture["x"] + picture["width"] / 2,
        picture["y"] + picture["height"] / 2,
    ) == {"path": "main.tex", "line": PICTURE_LINE}


def test_title_page_from_class_macro_is_not_student_text(
    compiler: Compiler, synctex: bytes
) -> None:
    for x, y in ((300, 80), (300, 100), (10, 10), (306, 760)):
        assert edit(compiler, synctex, 1, x, y) is None
    # Курсор на \titul и в преамбуле: synctex ищет ближайшую строку с текстом — здесь это
    # листинг из main.tex, — но титульный лист не подсвечивается.
    for line in range(1, TITLE_LINE + 1):
        boxes = view(compiler, synctex, "main.tex", line)
        assert all(box["page"] != 1 for box in boxes), line


def test_page_number_and_empty_space_are_not_student_text(
    compiler: Compiler, synctex: bytes
) -> None:
    # Документ короткий: низ страницы пуст, внизу только номер страницы.
    for y in (650, 700, 720, 780):
        assert edit(compiler, synctex, 2, 306, y) is None
    # Строка \end{document}, на которой страница ушла в печать, — не номер страницы внизу, а
    # ближайший текст выше.
    boxes = view(compiler, synctex, "main.tex", END_LINE)
    assert all(box["y"] + box["height"] < 650 for box in boxes)


def test_page_beyond_pdf_and_file_not_in_build(compiler: Compiler, synctex: bytes) -> None:
    assert edit(compiler, synctex, 5, 300, 300) is None
    assert view(compiler, synctex, "meta.tex", 1) == []
    # Путь сравнивается целиком, а не по концу имени.
    assert view(compiler, synctex, "цель.tex", 1) == []


def test_queries_leave_no_files(compiler: Compiler, synctex: bytes) -> None:
    view(compiler, synctex, GOAL, 1)
    edit(compiler, synctex, 2, 300, 100)

    assert "synctex-" not in compiler.exec("ls", "-a", "/tmp")


def test_broken_file_is_rejected(compiler: Compiler) -> None:
    response = compiler.synctex("edit", b"not gzip", page=1, x=1, y=1)

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["type"] == "invalid_synctex"
