"""Документы, архивы и вызов docker для тестов."""

import io
import json
import subprocess
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

COMPILER_DIR = Path(__file__).resolve().parents[1]
IMAGE = "blablatex-compiler:dev"

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
    *args: str, stdin: bytes | None = None, check: bool = True, timeout: float = 600
) -> subprocess.CompletedProcess[bytes]:
    """Запускает docker CLI и возвращает его вывод."""
    return subprocess.run(
        ["docker", *args], input=stdin, capture_output=True, check=check, timeout=timeout
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
