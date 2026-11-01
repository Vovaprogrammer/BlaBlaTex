"""Общие фикстуры тестов."""

import subprocess
from collections.abc import Iterator

import pytest

from tests.support import COMPILER_DIR, IMAGE, Compiler, docker


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


@pytest.fixture(scope="session")
def compiler(image: str) -> Iterator[Compiler]:
    """Сервис в контейнере. --init: процессы, убитые по таймауту, не остаются зомби."""
    container = (
        docker("run", "--detach", "--init", "--publish", "127.0.0.1::8080", image)
        .stdout.decode()
        .strip()
    )
    try:
        address = docker("port", container, "8080/tcp").stdout.decode().splitlines()[0]
        service = Compiler(url=f"http://{address}", container=container)
        service.wait_healthy()
        yield service
    finally:
        docker("rm", "--force", container, check=False)
