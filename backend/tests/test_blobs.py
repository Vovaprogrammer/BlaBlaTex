"""Уборка хранилища (architecture.md 5, «Уборка хранилища»): замок на blob, гонка
с загрузкой такого же файла, ночная уборка ничьих blob'ов."""

import asyncio
import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import blob_locks
from app.core.storage import LocalStorage
from app.modules.blobs import service as blobs_service
from app.modules.blobs import tasks as blobs_tasks
from app.modules.builds.models import Build
from app.modules.projects.models import File
from tests.build_worker import BuildWorker
from tests.file_samples import JPEG, PNG
from tests.helpers import backdate_changesets
from tests.live_builds import Live, new_project
from tests.test_builds_api import MAIN_TEX, built, write
from tests.test_uploads import saved, upload

# Any в этом файле — проект как JSON из ответа API.
DATA = b"same lab manual"
DATA_SHA = hashlib.sha256(DATA).hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def age(storage: LocalStorage, sha256: str, hours: float) -> None:
    """Делает blob старше на hours часов — как будто его записали давно."""
    old = time.time() - hours * 3600
    os.utime(storage.path(sha256), (old, old))


async def add_file(session: AsyncSession, project_id: uuid.UUID, sha256: str) -> None:
    """Ссылка на blob — как у загруженного файла; коммит — за вызывающим."""
    session.add(
        File(
            project_id=project_id,
            path="materials/manual.pdf",
            kind="binary",
            role="material",
            blob_sha256=sha256,
            mime="application/pdf",
            size=len(DATA),
            version=100,
        )
    )
    await session.flush()


# Гонка уборки и записи — на отдельных соединениях: в одной транзакции её не увидеть.


async def test_cleanup_waits_for_writer_and_keeps_blob_it_references(live: Live) -> None:
    project_id = await new_project(live)
    async with live.sessionmaker() as writer, live.sessionmaker() as cleaner:
        sha256 = await blob_locks.put_held(writer, live.storage, DATA)
        await add_file(writer, project_id, sha256)
        cleanup = asyncio.create_task(
            blobs_service.delete_unreferenced(cleaner, live.storage, [sha256])
        )
        await asyncio.sleep(0.3)
        # Ссылка ещё не закоммичена, но уборка ждёт замка, а не удаляет.
        assert not cleanup.done()
        await writer.commit()
        result = await asyncio.wait_for(cleanup, 5)

    assert (result.deleted, result.kept) == (0, 1)
    assert await live.storage.exists(sha256)


class CleanedRightAfterPut(LocalStorage):
    """Хранилище, у которого уборка срабатывает сразу после записи blob — до замка."""

    def __init__(self, live: Live) -> None:
        super().__init__(live.storage.root)
        self.live = live
        self.cleaned = 0

    async def put(self, data: bytes) -> str:
        sha256 = await super().put(data)
        if not self.cleaned:
            async with self.live.sessionmaker() as cleaner:
                result = await blobs_service.delete_unreferenced(cleaner, self, [sha256])
            self.cleaned = result.deleted
        return sha256


async def test_writer_puts_blob_again_if_cleanup_removed_it(live: Live) -> None:
    project_id = await new_project(live)
    storage = CleanedRightAfterPut(live)

    async with live.sessionmaker() as writer:
        sha256 = await blob_locks.put_held(writer, storage, DATA)
        await add_file(writer, project_id, sha256)
        await writer.commit()

    # Уборка успела удалить blob, но запись положила его снова.
    assert storage.cleaned == 1
    assert await storage.get(sha256) == DATA


async def test_cleanup_removes_blob_nobody_references(live: Live) -> None:
    sha256 = await live.storage.put(DATA)

    async with live.sessionmaker() as cleaner:
        result = await blobs_service.delete_unreferenced(cleaner, live.storage, [sha256])

    assert (result.deleted, result.kept, result.failed) == (1, 0, 0)
    assert not await live.storage.exists(sha256)


# Кто ссылается на blob и ночная уборка.


async def test_files_revisions_and_builds_reference_blobs(
    user_client: AsyncClient,
    project: dict[str, Any],
    db_session: AsyncSession,
    build_worker: BuildWorker,
) -> None:
    pid = project["id"]
    saved(await upload(user_client, project, ("photo.jpg", JPEG)))
    await backdate_changesets(db_session, uuid.UUID(pid))
    await db_session.commit()
    # Прежнее фото остаётся только в ревизии.
    saved(await upload(user_client, project, ("photo.jpg", JPEG + b"\n")))
    await write(user_client, pid, "main.tex", MAIN_TEX)
    build_id = uuid.UUID((await built(user_client, build_worker, pid))["id"])
    build = await db_session.scalar(select(Build).where(Build.id == build_id))
    assert build is not None and build.pdf_sha256 and build.log_sha256
    expected = {sha(JPEG), sha(JPEG + b"\n"), build.pdf_sha256, build.log_sha256}

    found = await blobs_service.referenced(db_session, [*expected, DATA_SHA])

    assert found == expected


async def test_sweep_removes_only_old_blobs_nobody_references(
    app: FastAPI, user_client: AsyncClient, project: dict[str, Any], db_session: AsyncSession
) -> None:
    storage: LocalStorage = app.state.storage
    saved(await upload(user_client, project, ("scheme.png", PNG)))
    used = sha(PNG)
    old_orphan = await storage.put(DATA)
    fresh_orphan = await storage.put(b"just uploaded, no reference yet")
    for sha256 in (used, old_orphan):
        age(storage, sha256, hours=2)

    result = await blobs_service.sweep(db_session, storage)

    assert (result.deleted, result.kept) == (1, 0)
    assert not await storage.exists(old_orphan)
    assert await storage.exists(used)
    assert await storage.exists(fresh_orphan)


async def test_listing_skips_unfinished_and_foreign_files(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "storage")
    sha256 = await storage.put(DATA)
    age(storage, sha256, hours=2)
    (storage.root / ".tmp-unfinished").write_bytes(b"x")
    (storage.path(sha256).parent / "notes.txt").write_bytes(b"x")

    assert await storage.list_older_than(blobs_service.MIN_AGE) == [sha256]
    assert await LocalStorage(tmp_path / "missing").list_older_than(blobs_service.MIN_AGE) == []


async def test_watcher_sweeps_after_delay_and_survives_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []
    done = asyncio.Event()

    async def sweep(session: object, storage: object) -> blobs_service.Cleanup:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("диск недоступен")
        done.set()
        return blobs_service.Cleanup(deleted=1)

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(blobs_service, "sweep", sweep)
    watcher = asyncio.create_task(
        blobs_tasks.watch_storage(
            Session,  # type: ignore[arg-type]
            LocalStorage(tmp_path),
            first_delay_s=0,
            interval_s=0,
        )
    )
    await asyncio.wait_for(done.wait(), 5)
    watcher.cancel()

    assert len(calls) >= 2
