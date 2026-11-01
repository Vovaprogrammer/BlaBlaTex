"""POST /compile против собранного образа: успешная сборка и ошибка LaTeX.

Таймаут и остановка всей группы процессов проверяются в test_attacks.py.
"""

import pytest

from tests.support import CYRILLIC_DOC, SIMPLE_DOC, Compiler

pytestmark = pytest.mark.container


def test_build_returns_pdf_log_and_synctex(compiler: Compiler) -> None:
    build = compiler.compile({"main.tex": CYRILLIC_DOC})

    assert build.result["status"] == "ok"
    assert build.result["exit_code"] == 0
    assert build.result["duration_ms"] > 0
    assert set(build.files) == {"result.json", "output.pdf", "output.log", "output.synctex.gz"}
    assert build.files["output.pdf"].startswith(b"%PDF")
    assert "This is XeTeX" in build.log


def test_pdflatex_engine(compiler: Compiler) -> None:
    build = compiler.compile({"main.tex": SIMPLE_DOC}, engine="pdflatex")

    assert build.result["status"] == "ok"
    assert "This is pdfTeX" in build.log


def test_main_file_in_subfolder(compiler: Compiler) -> None:
    files = {"report/lab.tex": r"\input{report/body}", "report/body.tex": SIMPLE_DOC}

    build = compiler.compile(files, main="report/lab.tex")

    assert build.result["status"] == "ok"
    assert build.files["output.pdf"].startswith(b"%PDF")


def test_latex_error_is_build_status_not_http_error(compiler: Compiler) -> None:
    doc = r"\documentclass{article}\begin{document}\undefinedmacro\end{document}"

    build = compiler.compile({"main.tex": doc})

    assert build.result["status"] == "error"
    assert build.result["exit_code"] not in (0, None)
    # -file-line-error: ошибка с файлом и строкой — по ним бэкенд покажет место в редакторе.
    assert "./main.tex:1: Undefined control sequence" in build.log
