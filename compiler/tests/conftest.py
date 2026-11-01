"""Общие фикстуры тестов."""

import subprocess

import pytest

from tests.support import COMPILER_DIR, IMAGE, docker


@pytest.fixture(scope="session")
def image() -> str:
    """Образ компилятора, собранный из текущих исходников. Собирается один раз за прогон."""
    try:
        docker("build", "--tag", IMAGE, str(COMPILER_DIR), timeout=3600)
    except FileNotFoundError:
        pytest.fail("Не найден docker: эти тесты гоняются против собранного образа.", pytrace=False)
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.decode(errors="replace")
        pytest.fail(f"Образ не собрался:\n{stderr}", pytrace=False)
    return IMAGE
