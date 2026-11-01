"""Общие фикстуры тестов."""

import subprocess
from collections.abc import Callable, Iterator

import pytest

from tests.support import COMPILER_DIR, IMAGE, Compiler, compose, docker


def _docker_step(step: Callable[[], object], what: str) -> None:
    try:
        step()
    except FileNotFoundError:
        pytest.fail("Не найден docker: эти тесты гоняются против собранного образа.", pytrace=False)
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.decode(errors="replace")
        pytest.fail(f"{what}:\n{stderr}", pytrace=False)


@pytest.fixture(scope="session")
def image() -> str:
    """Образ компилятора, собранный из текущих исходников. Собирается один раз за прогон."""
    _docker_step(
        lambda: docker("build", "--tag", IMAGE, str(COMPILER_DIR), timeout=3600),
        "Образ не собрался",
    )
    return IMAGE


@pytest.fixture(scope="session")
def compiler(image: str) -> Iterator[Compiler]:
    """Своя копия сервиса из docker-compose.yml: те же флаги, лимиты и сеть, что в dev."""
    try:
        _docker_step(
            lambda: compose("up", "--detach", "--wait", "compiler", "compiler-proxy"),
            "Компилятор не поднялся в docker compose",
        )
        address = compose("port", "compiler-proxy", "8080").stdout.decode().strip()
        container = compose("ps", "--quiet", "compiler").stdout.decode().strip()
        service = Compiler(url=f"http://{address}", container=container)
        service.wait_healthy()
        yield service
    finally:
        compose("down", "--remove-orphans", check=False)
