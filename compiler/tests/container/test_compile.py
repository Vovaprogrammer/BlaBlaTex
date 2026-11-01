"""POST /compile против собранного образа: успешная сборка, ошибка LaTeX, таймаут."""

import pytest

from tests.support import CYRILLIC_DOC, SIMPLE_DOC, Compiler, wait_until

pytestmark = pytest.mark.container

# \x вызывает сам себя: TeX крутится вечно и ничего не выводит.
ENDLESS_LOOP_DOC = r"""
\documentclass{article}
\begin{document}
\def\x{\x}\x
\end{document}
"""


def test_build_returns_pdf_log_and_synctex(compiler: Compiler) -> None:
    build = compiler.compile({"main.tex": CYRILLIC_DOC})

    assert build.result["status"] == "ok"
    assert build.result["exit_code"] == 0
    assert build.result["duration_ms"] > 0
    assert set(build.files) == {"result.json", "output.pdf", "output.log", "output.synctex.gz"}
    assert build.files["output.pdf"].startswith(b"%PDF")
    assert "This is XeTeX" in build.log


@pytest.mark.parametrize(
    ("engine", "banner"), [("pdflatex", "This is pdfTeX"), ("lualatex", "This is LuaHBTeX")]
)
def test_other_engines(compiler: Compiler, engine: str, banner: str) -> None:
    build = compiler.compile({"main.tex": SIMPLE_DOC}, engine=engine)

    assert build.result["status"] == "ok"
    assert banner in build.log


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


def test_timeout_kills_whole_process_group(compiler: Compiler) -> None:
    build = compiler.compile({"main.tex": ENDLESS_LOOP_DOC}, timeout_s=3)

    assert build.result == {
        "status": "timeout",
        "exit_code": None,
        "duration_ms": build.result["duration_ms"],
    }
    assert 3000 <= build.result["duration_ms"] < 10_000
    assert "output.pdf" not in build.files
    # Убит не только latexmk, но и запущенный им xelatex.
    wait_until(
        lambda: not any(name in compiler.processes() for name in ("latexmk", "xelatex")),
        timeout=10,
        message="После таймаута в контейнере остались процессы сборки",
    )
