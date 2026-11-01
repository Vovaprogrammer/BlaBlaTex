"""Безопасная распаковка проекта и упаковка результата сборки (architecture.md 9.7, 9.8)."""

import gzip
import io
import json
import tarfile
import zlib
from pathlib import Path
from typing import IO, Any

MB = 1024 * 1024
MAX_ARCHIVE_BYTES = 200 * MB
MAX_UNPACKED_BYTES = 200 * MB
MAX_FILES = 10_000


class ArchiveError(Exception):
    """Архив битый или небезопасный. Сообщение — для бэкенда, на русском."""


class ArchiveTooLargeError(Exception):
    """Архив больше лимитов 9.8."""


def is_safe_relative_path(path: str) -> bool:
    """Относительный путь через «/» без «.», «..», пустых сегментов, «\\» и управляющих символов."""
    if not path or path.startswith("/") or "\\" in path:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def extract_project(archive: IO[bytes], dest: Path) -> None:
    """Распаковывает tar.gz в dest: только обычные файлы и папки, в пределах лимитов.

    Ссылки отклоняются целиком: symlink на /etc/passwd внутри проекта TeX прочитал бы
    как обычный файл, и openin_any его бы не остановил.
    """
    try:
        with tarfile.open(fileobj=archive, mode="r:gz") as tar:
            members = _checked_members(tar)
            dest.mkdir(parents=True)
            # Фильтр data — вторая линия защиты: сбрасывает setuid и права владельца.
            tar.extractall(dest, members=members, filter="data")
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as error:
        raise ArchiveError("Архив повреждён или это не tar.gz") from error


def _checked_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    unpacked = 0
    for member in tar:
        if not (member.isfile() or member.isdir()):
            raise ArchiveError(f"В архиве ссылка или особый файл: {member.name}")
        if not is_safe_relative_path(member.name):
            raise ArchiveError(f"Недопустимый путь в архиве: {member.name}")
        members.append(member)
        unpacked += member.size
        if len(members) > MAX_FILES:
            raise ArchiveTooLargeError(f"В архиве больше {MAX_FILES} файлов")
        if unpacked > MAX_UNPACKED_BYTES:
            raise ArchiveTooLargeError(
                f"Проект в распакованном виде больше {MAX_UNPACKED_BYTES // MB} МБ"
            )
    return members


def pack_result(result: dict[str, Any], files: dict[str, Path]) -> bytes:
    """tar.gz ответа: result.json и те файлы из files, которые существуют."""
    buffer = io.BytesIO()
    # PDF уже сжат — сильнее сжимать нет смысла, только трата процессора.
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=1) as tar:
        data = json.dumps(result).encode()
        info = tarfile.TarInfo("result.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for name, path in files.items():
            if path.is_file():
                tar.add(path, arcname=name, recursive=False)
    return buffer.getvalue()
