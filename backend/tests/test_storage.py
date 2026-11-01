"""Хранилище файлов по sha256 на диске (LocalStorage)."""

import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.storage import CHUNK_SIZE, BlobNotFoundError, LocalStorage, Storage

PDF = b"%PDF-1.7 test"
PDF_SHA = hashlib.sha256(PDF).hexdigest()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


def stored_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


async def test_put_returns_sha256_and_lays_out_by_prefix(storage: LocalStorage) -> None:
    sha256 = await storage.put(PDF)

    assert sha256 == PDF_SHA
    assert stored_files(storage.root) == [storage.root / PDF_SHA[:2] / PDF_SHA[2:4] / PDF_SHA]


async def test_same_content_is_stored_once(storage: LocalStorage) -> None:
    first = await storage.put(PDF)
    second = await storage.put(PDF)

    assert first == second
    # Временных файлов после записи тоже не остаётся.
    assert len(stored_files(storage.root)) == 1


async def test_get_and_exists(storage: LocalStorage) -> None:
    sha256 = await storage.put(PDF)

    assert await storage.get(sha256) == PDF
    assert await storage.exists(sha256)
    assert not await storage.exists("0" * 64)


async def test_empty_content_is_a_valid_file(storage: LocalStorage) -> None:
    sha256 = await storage.put(b"")

    assert await storage.get(sha256) == b""


async def test_get_missing_raises_not_found(storage: LocalStorage) -> None:
    with pytest.raises(BlobNotFoundError):
        await storage.get("0" * 64)


async def test_delete_removes_file_and_ignores_missing(storage: LocalStorage) -> None:
    sha256 = await storage.put(PDF)

    await storage.delete(sha256)
    await storage.delete(sha256)

    assert not await storage.exists(sha256)


async def test_open_stream_returns_content_in_chunks(storage: LocalStorage) -> None:
    data = bytes(range(256)) * (CHUNK_SIZE // 256 * 2 + 1)
    sha256 = await storage.put(data)

    chunks = [chunk async for chunk in await storage.open_stream(sha256)]

    assert len(chunks) == 3
    assert b"".join(chunks) == data


async def test_open_stream_of_missing_file_fails_before_first_chunk(
    storage: LocalStorage,
) -> None:
    # Ошибка должна прийти при открытии: когда поток уже отдаётся, ответ 404 не отправить.
    with pytest.raises(BlobNotFoundError):
        await storage.open_stream("0" * 64)


@pytest.mark.parametrize(
    "sha256",
    ["../../etc/passwd", PDF_SHA.upper(), PDF_SHA[:-1], PDF_SHA + "0", f"../{PDF_SHA[3:]}", ""],
    ids=["traversal", "uppercase", "short", "long", "traversal-64", "empty"],
)
async def test_rejects_anything_but_sha256(storage: LocalStorage, sha256: str) -> None:
    for call in (storage.get, storage.exists, storage.delete, storage.open_stream):
        with pytest.raises(ValueError, match="sha256"):
            await call(sha256)


def test_app_storage_lives_in_settings_dir(app: FastAPI, settings: Settings) -> None:
    storage: Storage = app.state.storage

    assert isinstance(storage, LocalStorage)
    assert storage.root == settings.storage_dir
