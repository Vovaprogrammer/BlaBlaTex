"""Версия сборочного окружения для кэша сборок бэкенда (architecture.md 6, 9.7).

Бэкенд кладёт её в ключ кэша: одинаковые файлы, собранные другим окружением, могут дать
другой PDF, и старый результат выдавать нельзя.
"""

import hashlib
import os
from pathlib import Path

# Общий класс шаблонов (TEXINPUTS в Dockerfile).
SHARED_TEX_DIR = Path("/opt/blablatex/tex")
# Вне образа (unit-тесты, локальный запуск) переменной нет.
_UNKNOWN_IMAGE = "dev"


def compiler_version(shared_dir: Path) -> str:
    """«<COMPILER_VERSION из Dockerfile>+<отпечаток общего класса>».

    Отпечаток считается при каждом вызове: в dev папка смонтирована с хоста,
    и класс меняется без пересборки образа.
    """
    image = os.environ.get("COMPILER_VERSION") or _UNKNOWN_IMAGE
    return f"{image}+{shared_fingerprint(shared_dir)}"


def shared_fingerprint(root: Path) -> str:
    """Короткий sha256 от путей и содержимого всех файлов папки. Нет папки — отпечаток пустой."""
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file()) if root.is_dir() else []
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:16]
