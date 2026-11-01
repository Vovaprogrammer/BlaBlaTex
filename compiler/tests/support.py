"""Документы, архивы и вызов docker для тестов."""

import io
import subprocess
import tarfile
from pathlib import Path

COMPILER_DIR = Path(__file__).resolve().parents[1]
IMAGE = "blablatex-compiler:dev"

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
