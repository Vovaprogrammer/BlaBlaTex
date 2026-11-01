"""Образ: TeX Live нужного года, шрифты Liberation и кириллица — без HTTP-сервиса."""

import pytest

from tests.support import CYRILLIC_DOC, docker, make_tar

pytestmark = pytest.mark.container

# Распаковать проект из stdin и собрать его той же командой, что и сервис.
BUILD_FROM_STDIN = (
    "mkdir /tmp/w && cd /tmp/w && tar -xzf - && "
    "latexmk -norc -xelatex -interaction=nonstopmode -file-line-error -synctex=1 "
    "-no-shell-escape -outdir=out main.tex > /dev/null; code=$?; "
    'cat out/main.log; test -s out/main.pdf && echo PDF_OK; echo "LATEXMK_EXIT=$code"'
)


def run(image: str, *command: str, stdin: bytes | None = None) -> str:
    result = docker("run", "--rm", "-i", "--network", "none", image, *command, stdin=stdin)
    return result.stdout.decode()


def test_tex_live_year_is_pinned(image: str) -> None:
    assert "TeX Live 2025" in run(image, "tex", "--version")


def test_liberation_fonts_installed(image: str) -> None:
    families = run(image, "fc-list", ":", "family")

    for family in ("Liberation Serif", "Liberation Sans", "Liberation Mono"):
        assert family in families


def test_runs_as_non_root_user(image: str) -> None:
    assert run(image, "id", "-u").strip() != "0"


def test_texinputs_includes_shared_class_dir(image: str) -> None:
    assert run(image, "printenv", "TEXINPUTS").strip() == ".:/opt/blablatex/tex//:"


def test_cyrillic_liberation_and_listings_compile(image: str) -> None:
    output = run(image, "bash", "-c", BUILD_FROM_STDIN, stdin=make_tar({"main.tex": CYRILLIC_DOC}))

    assert "LATEXMK_EXIT=0" in output
    assert "PDF_OK" in output
    # Так fontspec называет в логе семейства, созданные для Liberation Serif и Mono.
    assert "TU/LiberationSerif(0)" in output
    assert "TU/LiberationMono(0)" in output
    assert "Missing character" not in output
