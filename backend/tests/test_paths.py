"""Правила путей файлов проекта (architecture.md 9.8): validate_path и ответ 422."""

import re

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.modules.projects.paths import InvalidPathError, validate_path
from app.modules.projects.schemas import FilePath, FolderCreate

ALLOWED = [
    "main.tex",
    "sections/goal.tex",
    "materials/Методичка ЛР 1.pdf",
    "code/my_file-v2.py",
    "a/b/c/d.tex",
    "file.with.dots.tex",
    # Скобки, пробелы и прочая пунктуация TeX не мешают: так называет копии Windows.
    "materials/Снимок экрана (1).png",
    "lab 1 [итог], v2; it's ok!.tex",
    "latexmkrc.tex",
    "x" * 100,
    "я" * 100,  # 200 байт
    "\U0001f600" * 63,  # 252 байта
    "/".join(["a" * 100, "b" * 100, "c" * 53]),  # ровно 255
]

FORBIDDEN = [
    ("", "пустым"),
    ("/etc/passwd", "начинаться с /"),
    ("/main.tex", "начинаться с /"),
    ("..", "«.» и «..»"),
    ("../secret.tex", "«.» и «..»"),
    ("sections/../../x.tex", "«.» и «..»"),
    ("a/..", "«.» и «..»"),
    ("./main.tex", "«.» и «..»"),
    ("a/./b.tex", "«.» и «..»"),
    ("a//b.tex", "двух / подряд"),
    ("sections/", "/ в конце"),
    ("sections\\goal.tex", "Символ \\"),
    ("..\\x.tex", "Символ \\"),
    ("C:/x.tex", "Символ :"),
    ("a:b.tex", "Символ :"),
    *((f"sections/a{char}b.tex", f"Символ {char} в имени ломает сборку") for char in '%#~$&^{}`"'),
    ("100%.txt", "Символ % в имени ломает сборку"),
    ("a\x00b.tex", "Управляющие"),
    ("a\nb.tex", "Управляющие"),
    ("a\tb.tex", "Управляющие"),
    ("a\x7fb.tex", "Управляющие"),
    ("report\u202excod.tex", "невидимые"),  # смена направления текста
    ("ma\u200bin.tex", "невидимые"),  # пробел нулевой ширины
    ("\ufeffmain.tex", "невидимые"),
    ("a\u2028b.tex", "невидимые"),
    ("a\ud800b.tex", "невидимые"),  # половинка суррогатной пары
    (".git/config", "с точки"),
    (".latexmkrc", "с точки"),
    ("sections/.hidden.tex", "с точки"),
    ("latexmkrc", "latexmkrc запрещено"),
    ("sub/latexmkrc", "latexmkrc запрещено"),
    ("LatexMkRc", "latexmkrc запрещено"),
    ("/".join(["a" * 100, "b" * 100, "c" * 54]), "Путь длиннее 255"),
    ("x" * 101, "длиннее 100"),
    ("\U0001f600" * 64, "слишком длинное"),  # 64 символа, но 256 байт
    ("sections/" + "字" * 86 + ".tex", "слишком длинное"),
]


@pytest.mark.parametrize("path", ALLOWED)
def test_allowed_path(path: str) -> None:
    assert validate_path(path) == path


@pytest.mark.parametrize(("path", "reason"), FORBIDDEN, ids=[repr(p) for p, _ in FORBIDDEN])
def test_forbidden_path(path: str, reason: str) -> None:
    with pytest.raises(InvalidPathError, match=re.escape(reason)):
        validate_path(path)


def test_path_is_normalized_to_nfc() -> None:
    # «й» из двух символов (и + кратка), как присылает macOS, становится одним.
    assert validate_path("отчёт/и\u0306.tex") == "отчёт/й.tex"


async def test_bad_path_in_request_is_validation_error_with_reason(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.post("/test-paths/{path:path}")
    async def route(path: FilePath, body: FolderCreate) -> None:
        raise AssertionError("до маршрута дело не доходит")

    response = await client.post("/test-paths/a%5Cb.tex", json={"path": "../x.tex"})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"] == [
        {"loc": ["path", "path"], "type": "invalid_path", "message": "Символ \\ в пути запрещён"},
        {
            "loc": ["body", "path"],
            "type": "invalid_path",
            "message": "Части пути «.» и «..» запрещены",
        },
    ]
