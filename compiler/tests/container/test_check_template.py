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


def test_broken_template_shows_file_and_line(compiler: Compiler) -> None:
    code, output = check_template("broken")

    assert code == 1
    assert "./main.tex:5: Undefined control sequence." in output


def test_template_without_sample_meta(compiler: Compiler) -> None:
    code, output = check_template("no-meta")

    assert code == 1
    assert "нет файла meta.sample.tex" in output
