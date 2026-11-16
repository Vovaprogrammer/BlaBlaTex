"""check-template в контейнере — той же командой, что в AGENTS.md и в CI шаблонов (T1.4)."""

import pytest

from tests.support import Compiler, compose

pytestmark = pytest.mark.container


def check_template(slug: str) -> tuple[int, str]:
    """docker compose run --rm compiler check-template templates/<slug>."""
    result = compose("run", "--rm", "compiler", "check-template", f"templates/{slug}", check=False)
    return result.returncode, result.stdout.decode(errors="replace")


def test_good_template_builds(compiler: Compiler) -> None:
    code, output = check_template("ok")

    assert code == 0, output
    assert "OK: templates/ok" in output


def test_main_and_engine_from_manifest(compiler: Compiler) -> None:
    code, output = check_template("own-main")

    assert code == 0, output
    assert "OK: templates/own-main собран" in output
    assert "(report.tex, pdflatex)" in output


def test_broken_template_shows_file_and_line(compiler: Compiler) -> None:
    code, output = check_template("broken")

    assert code == 1
    # Путь — от корня репозитория, под ним строка исходника с неизвестным макросом.
    assert (
        "templates/broken/main.tex:5: Undefined control sequence.\nl.5 \\bbtNoSuchMacro" in output
    )


def test_several_templates_with_annotations(compiler: Compiler) -> None:
    # Так их собирает CI шаблонов: одной командой, с пометками GitHub.
    result = compose(
        "run",
        "--rm",
        "compiler",
        "check-template",
        "--github",
        "templates/ok",
        "templates/broken",
        check=False,
    )
    output = result.stdout.decode(errors="replace")

    assert result.returncode == 1
    assert "OK: templates/ok собран" in output
    assert (
        "::error file=templates/broken/main.tex,line=5,title=templates/broken не собирается::"
        "Undefined control sequence.%0Al.5 \\bbtNoSuchMacro"
    ) in output
    assert output.rstrip().endswith("Собрано 1 из 2. С ошибками: templates/broken")


def test_template_without_sample_meta(compiler: Compiler) -> None:
    code, output = check_template("no-meta")

    assert code == 1
    assert "нет файла meta.sample.tex" in output
