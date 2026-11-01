"""Документы, архивы и вызов docker для тестов."""

import io
import json
import os
import subprocess
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

COMPILER_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = COMPILER_DIR.parent
IMAGE = "blablatex-compiler:dev"

# Отдельный проект compose: тесты не трогают рабочие контейнеры разработчика.
TEST_PROJECT = "blablatex-compiler-test"
DEV_COMPOSE = REPO_DIR / "docker-compose.yml"
TEST_COMPOSE = COMPILER_DIR / "tests" / "compose.test.yml"
# compose проверяет обязательные переменные всего файла, даже у сервисов, которые не
# запускаются. Postgres тесты не поднимают — пароль нужен только для этой проверки.
COMPOSE_ENV = {**os.environ, "POSTGRES_PASSWORD": "not-used-by-compiler-tests"}

SIMPLE_DOC = r"""
\documentclass{article}
\begin{document}
Hello
\end{document}
"""

# Кириллица, Liberation Serif и listings — то, на чём держатся шаблоны отчётов.
# \tracinglostchars=2 пишет в лог «Missing character», если в шрифте нет буквы.
CYRILLIC_DOC = r"""
\documentclass{article}
\usepackage{fontspec}
\setmainfont{Liberation Serif}
\setmonofont{Liberation Mono}
\usepackage[russian]{babel}
\usepackage{listings}
\lstset{basicstyle=\ttfamily, extendedchars=true}
\tracinglostchars=2
\begin{document}
Съешь же ещё этих мягких французских булок, да выпей чаю. Ёлка, ЙЦУКЕН.
\begin{lstlisting}[language=Python]
def hello():
    print("Привет")  # комментарий по-русски
\end{lstlisting}
\end{document}
"""


def make_tar(files: dict[str, str | bytes]) -> bytes:
    """tar.gz из словаря «путь → содержимое»: так бэкенд передаёт проект в компилятор."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def docker(
    *args: str,
    stdin: bytes | None = None,
    check: bool = True,
    timeout: float = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Запускает docker CLI и возвращает его вывод."""
    return subprocess.run(
        ["docker", *args], input=stdin, capture_output=True, check=check, timeout=timeout, env=env
    )


def compose(
    *args: str, check: bool = True, timeout: float = 600
) -> subprocess.CompletedProcess[bytes]:
    """docker compose тестового проекта: docker-compose.yml и поверх него compose.test.yml.

    Образ берётся готовый — его собирает фикстура image из текущих исходников.
    """
    return docker(
        "compose",
        "--project-name",
        TEST_PROJECT,
        "--project-directory",
        str(REPO_DIR),
        "--file",
        str(DEV_COMPOSE),
        "--file",
        str(TEST_COMPOSE),
        *args,
        check=check,
        timeout=timeout,
        env=COMPOSE_ENV,
    )


def wait_until(condition: Callable[[], bool], timeout: float = 30, message: str = "") -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(message or "Не дождались условия")
        time.sleep(0.5)


@dataclass(frozen=True)
class Build:
    """Распакованный ответ POST /compile."""

    result: dict[str, Any]
    files: dict[str, bytes]

    @property
    def log(self) -> str:
        return self.files["output.log"].decode(errors="replace")


@dataclass(frozen=True)
class Compiler:
    """Запущенный контейнер компилятора: адрес сервиса и id контейнера."""

    url: str
    container: str

    def post(self, files: dict[str, str | bytes], **fields: str | int) -> httpx.Response:
        archive = ("project.tar.gz", make_tar(files), "application/gzip")
        return httpx.post(
            f"{self.url}/compile",
            files={"archive": archive},
            data={name: str(value) for name, value in fields.items()},
            timeout=180,
        )

    def compile(self, files: dict[str, str | bytes], **fields: str | int) -> Build:
        response = self.post(files, **fields)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/gzip"
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
            contents = {
                member.name: tar.extractfile(member).read()  # type: ignore[union-attr]
                for member in tar
            }
        return Build(json.loads(contents["result.json"]), contents)

    def processes(self) -> str:
        """Процессы внутри контейнера, как их видит docker top."""
        return docker("top", self.container, "-eo", "pid,args").stdout.decode()

    def wait_healthy(self) -> None:
        def healthy() -> bool:
            try:
                return httpx.get(f"{self.url}/health", timeout=2).status_code == 200
            except httpx.HTTPError:
                return False

        wait_until(healthy, timeout=60, message=f"Компилятор не ответил на {self.url}/health")
