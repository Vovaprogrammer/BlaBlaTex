"""Хранилище файлов по sha256 (architecture.md 5): бинарные файлы проектов и артефакты сборок.

Файл адресуется хешем своего содержимого: одинаковые файлы лежат один раз, а записанный
файл больше не меняется. Сейчас это папка на диске (в проде — volume Docker), позже
при необходимости — S3-совместимое хранилище с тем же интерфейсом.
"""

import asyncio
import hashlib
import os
import re
import tempfile
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import IO, Annotated, Protocol

from fastapi import Depends, Request

# Кусок при отдаче потоком: PDF до 50 МБ не читается в память целиком.
CHUNK_SIZE = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


class BlobNotFoundError(Exception):
    """В хранилище нет файла с таким sha256."""


class Storage(Protocol):
    """Файлы по sha256 их содержимого. Все методы асинхронные: диск или сеть не блокируют API."""

    async def put(self, data: bytes) -> str:
        """Сохраняет данные и возвращает их sha256. Такой файл уже есть — ничего не пишет."""
        ...

    async def get(self, sha256: str) -> bytes:
        """Содержимое целиком. Нет файла — BlobNotFoundError."""
        ...

    async def exists(self, sha256: str) -> bool: ...

    async def delete(self, sha256: str) -> None:
        """Удаляет файл; если его уже нет — ничего не делает."""
        ...

    async def open_stream(self, sha256: str) -> AsyncIterator[bytes]:
        """Открывает файл и возвращает его содержимое кусками.

        Нет файла — BlobNotFoundError сразу, ещё до первого куска: HTTP-ответ успеет стать 404.
        """
        ...


class LocalStorage:
    """Хранилище в папке на диске: root/ab/cd/<sha256>.

    Две вложенные папки по началу хеша — чтобы в одной папке не копились сотни тысяч файлов.
    Работа с диском идёт в отдельном потоке.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, sha256: str) -> Path:
        """Путь файла. sha256 проверяется: строка вроде «../../etc/passwd» сюда не пройдёт."""
        if not _SHA256.fullmatch(sha256):
            raise ValueError("Ожидается sha256: 64 символа 0-9 и a-f")
        return self.root / sha256[:2] / sha256[2:4] / sha256

    async def put(self, data: bytes) -> str:
        return await asyncio.to_thread(self._put, data)

    async def get(self, sha256: str) -> bytes:
        path = self.path(sha256)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise BlobNotFoundError(sha256) from None

    async def exists(self, sha256: str) -> bool:
        return await asyncio.to_thread(self.path(sha256).is_file)

    async def delete(self, sha256: str) -> None:
        await asyncio.to_thread(self.path(sha256).unlink, missing_ok=True)

    async def open_stream(self, sha256: str) -> AsyncIterator[bytes]:
        path = self.path(sha256)
        try:
            file = await asyncio.to_thread(path.open, "rb")
        except FileNotFoundError:
            raise BlobNotFoundError(sha256) from None
        return _read_chunks(file)

    def _put(self, data: bytes) -> str:
        sha256 = hashlib.sha256(data).hexdigest()
        path = self.path(sha256)
        if path.is_file():
            return sha256
        path.parent.mkdir(parents=True, exist_ok=True)
        # Пишем во временный файл рядом и переименовываем: недописанный файл никто не увидит,
        # а одновременная запись того же содержимого просто заменит файл таким же.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                # На диск до переименования: после сбоя питания в базе не останется ссылки
                # на пустой файл.
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        return sha256


async def _read_chunks(file: IO[bytes]) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(file.read, CHUNK_SIZE):
            yield chunk
    finally:
        file.close()


def get_storage(request: Request) -> Storage:
    """Хранилище приложения; его создаёт create_app()."""
    storage: Storage = request.app.state.storage
    return storage


StorageDep = Annotated[Storage, Depends(get_storage)]
