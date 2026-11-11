"""Экспорт проекта архивом (architecture.md 9.1, «Экспорт»): состав, байты, русские имена,
сжатие, доступ, память и снимок файлов на один момент."""

import asyncio
import io
import tracemalloc
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage
from app.modules.projects import export
from app.modules.projects import service as projects_service
from app.modules.projects.dependencies import get_shared_dir
from app.modules.projects.models import File, Project
from tests.file_samples import DOCX, PDF, PNG, XLSX
from tests.helpers import CSRF, create_empty_project, writer
from tests.live_builds import Live
from tests.test_bearer_auth import issue_token, use_token

API = "/api/v1"
REPO_SHARED = Path(__file__).parents[2] / "templates" / "_shared"
CLASS_NAME = "test-report.cls"
CLASS_TEXT = "% класс для тестов экспорта\n"
HOWTO = export.HOWTO_NAME
# Any — проект как JSON из ответа API.
Json = dict[str, Any]


@pytest.fixture
def shared_dir(app: FastAPI, tmp_path: Path) -> Path:
    """Папка общего класса с одним файлом и скрытым, который в архив не идёт."""
    folder = tmp_path / "_shared"
    folder.mkdir()
    (folder / CLASS_NAME).write_bytes(CLASS_TEXT.encode())
    (folder / ".gitkeep").write_bytes(b"")
    app.dependency_overrides[get_shared_dir] = lambda: folder
    return folder


async def upload(
    client: AsyncClient, project: Json, *files: tuple[str, bytes], folder: str = "materials"
) -> None:
    parts = [("files", (name, data)) for name, data in files]
    response = await client.post(
        f"{API}/projects/{project['id']}/upload", files=parts, data={"dir": folder}
    )
    assert response.status_code == 200, response.text


async def put(client: AsyncClient, project: Json, path: str, text: str) -> None:
    response = await client.put(f"{API}/projects/{project['id']}/files/{path}", content=text)
    assert response.status_code in (200, 201), response.text


async def set_last_name(client: AsyncClient, last_name: str) -> None:
    profile = {
        "last_name": last_name,
        "first_name": "Владимир",
        "middle_name": "",
        "group_name": "БВТ2201",
        "faculty": "",
        "department": "",
    }
    response = await client.put(f"{API}/profile", json=profile, headers=CSRF)
    assert response.status_code == 200, response.text


async def download(client: AsyncClient, project: Json, query: str = "") -> zipfile.ZipFile:
    response = await client.get(f"{API}/projects/{project['id']}/export.zip{query}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-length"] == str(len(response.content))
    return zipfile.ZipFile(io.BytesIO(response.content))


async def project_files(client: AsyncClient, project: Json) -> dict[str, bytes | None]:
    """Путь → содержимое из API; у папки — None."""
    tree = (await client.get(f"{API}/projects/{project['id']}/tree")).json()["items"]
    files: dict[str, bytes | None] = {}
    for item in tree:
        if item["kind"] == "folder":
            files[item["path"]] = None
            continue
        response = await client.get(f"{API}/projects/{project['id']}/files/{item['path']}")
        assert response.status_code == 200, response.text
        files[item["path"]] = response.content
    return files


async def materials_project(client: AsyncClient, project: Json) -> None:
    await upload(
        client,
        project,
        ("Скриншот окна.png", PNG),
        ("lab.py", "print('привет')\n".encode()),
        ("Методичка.pdf", PDF),
        ("задание.docx", DOCX),
        ("замеры.xlsx", XLSX),
    )
    await upload(client, project, ("plot.png", PNG), folder="Рисунки")
    await put(client, project, "sections/Ход работы.tex", "\\section{Ход работы}\nТекст.\n")
    response = await client.post(
        f"{API}/projects/{project['id']}/folders", json={"path": "Пустая папка"}
    )
    assert response.status_code == 201, response.text


def members(archive: zipfile.ZipFile) -> dict[str, bytes | None]:
    """Имя в архиве (папка — без / в конце) → содержимое; у папки — None."""
    return {
        info.filename.removesuffix("/"): None if info.is_dir() else archive.read(info)
        for info in archive.infolist()
    }


@pytest.mark.usefixtures("shared_dir")
async def test_archive_has_build_files_with_their_bytes(
    user_client: AsyncClient, project: Json
) -> None:
    await materials_project(user_client, project)
    files = await project_files(user_client, project)

    archive = await download(user_client, project)

    content = members(archive)
    documents = {"materials/Методичка.pdf", "materials/задание.docx", "materials/замеры.xlsx"}
    expected = {path: data for path, data in files.items() if path not in documents}
    assert {path: content[path] for path in expected} == expected
    assert set(content) == set(expected) | {CLASS_NAME, HOWTO}
    assert content[CLASS_NAME] == CLASS_TEXT.encode()
    assert "meta.tex" in content
    # Пустая папка — тоже запись, и папка, где остались одни документы.
    assert content["Пустая папка"] is None
    assert content["materials"] is None
    assert archive.testzip() is None


@pytest.mark.usefixtures("shared_dir")
async def test_with_materials_adds_documents(user_client: AsyncClient, project: Json) -> None:
    await materials_project(user_client, project)
    files = await project_files(user_client, project)

    archive = await download(user_client, project, "?with_materials=1")

    content = members(archive)
    assert {path: content[path] for path in files} == files
    assert set(content) == set(files) | {CLASS_NAME, HOWTO}


@pytest.mark.usefixtures("shared_dir")
async def test_names_are_utf8_and_paths_stay_inside(
    user_client: AsyncClient, project: Json
) -> None:
    await materials_project(user_client, project)

    archive = await download(user_client, project, "?with_materials=1")

    for info in archive.infolist():
        name = info.filename
        assert not name.startswith("/") and "\\" not in name and ":" not in name
        assert all(part not in ("", ".", "..") for part in name.removesuffix("/").split("/"))
        # Флаг UTF-8 (бит 11) — у каждого имени не из ASCII: так его читают Windows и macOS.
        assert bool(info.flag_bits & 0x800) == (not name.isascii()), name
    folder = archive.getinfo("Рисунки/")
    assert folder.is_dir()
    assert folder.external_attr >> 16 == 0o40755


@pytest.mark.usefixtures("shared_dir")
async def test_compressed_files_are_stored_and_text_deflated(
    user_client: AsyncClient, project: Json
) -> None:
    await materials_project(user_client, project)

    archive = await download(user_client, project, "?with_materials=1")

    stored = ["materials/Скриншот окна.png", "materials/Методичка.pdf", "materials/задание.docx"]
    for name in stored:
        assert archive.getinfo(name).compress_type == zipfile.ZIP_STORED, name
    for name in ("main.tex", "materials/lab.py", CLASS_NAME, HOWTO):
        assert archive.getinfo(name).compress_type == zipfile.ZIP_DEFLATED, name


async def test_project_file_wins_over_class_and_howto(
    user_client: AsyncClient, project: Json, shared_dir: Path
) -> None:
    await put(user_client, project, CLASS_NAME, "% свой класс студента\n")
    await put(user_client, project, HOWTO, "Мои заметки\n")

    archive = await download(user_client, project)

    names = [info.filename for info in archive.infolist()]
    assert names.count(CLASS_NAME) == 1 and names.count(HOWTO) == 1
    assert archive.read(CLASS_NAME) == "% свой класс студента\n".encode()
    assert archive.read(HOWTO) == "Мои заметки\n".encode()


@pytest.mark.usefixtures("shared_dir")
async def test_howto_names_main_file(user_client: AsyncClient, project: Json) -> None:
    archive = await download(user_client, project)

    howto = archive.read(HOWTO).decode()
    assert "latexmk -xelatex main.tex" in howto
    assert "XeLaTeX" in howto and "Liberation" in howto and "meta.tex" in howto


async def test_real_shared_class_goes_to_archive(
    app: FastAPI, user_client: AsyncClient, project: Json
) -> None:
    app.dependency_overrides[get_shared_dir] = lambda: REPO_SHARED

    archive = await download(user_client, project)

    assert archive.read("mtuci-report.cls") == (REPO_SHARED / "mtuci-report.cls").read_bytes()


async def test_missing_shared_dir_still_gives_sources(
    app: FastAPI, user_client: AsyncClient, project: Json, tmp_path: Path
) -> None:
    app.dependency_overrides[get_shared_dir] = lambda: tmp_path / "нет такой папки"

    archive = await download(user_client, project)

    assert "main.tex" in archive.namelist() and HOWTO in archive.namelist()


@pytest.mark.usefixtures("shared_dir")
async def test_archive_name_from_fields_and_profile(
    user_client: AsyncClient, project: Json
) -> None:
    await set_last_name(user_client, "Чистяков")

    response = await user_client.get(f"{API}/projects/{project['id']}/export.zip")

    name = quote("ЛР1_Чистяков.zip", safe="")
    assert response.headers["content-disposition"] == (
        f"attachment; filename=\"__1_________.zip\"; filename*=UTF-8''{name}"
    )
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_foreign_project_is_not_found(
    user_client: AsyncClient, project: Json, sign_up: Any
) -> None:
    await sign_up("other@example.com")

    response = await user_client.get(f"{API}/projects/{project['id']}/export.zip")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_token_cannot_export(user_client: AsyncClient, project: Json) -> None:
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    response = await user_client.get(f"{API}/projects/{project['id']}/export.zip")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.usefixtures("shared_dir")
async def test_missing_blob_is_reported_with_path(
    app: FastAPI, user_client: AsyncClient, project: Json
) -> None:
    await upload(user_client, project, ("shot.png", PNG))
    for path in app.state.settings.storage_dir.rglob("*"):
        if path.is_file():
            path.unlink()

    response = await user_client.get(f"{API}/projects/{project['id']}/export.zip")

    assert response.status_code == 404
    assert "materials/shot.png" in response.json()["error"]["message"]


async def test_big_file_is_streamed_not_loaded(
    app: FastAPI,
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Json,
    shared_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    big = PNG + bytes(15 * 1024 * 1024)
    await upload(user_client, project, ("big.png", big))
    storage: Storage = app.state.storage

    async def whole_blob(sha256: str) -> bytes:
        raise AssertionError("blob прочитан в память целиком")

    monkeypatch.setattr(storage, "get", whole_blob)
    row = await projects_service.get_project(db_session, uuid.UUID(project["id"]))
    assert row is not None

    tracemalloc.start()
    try:
        archive, size = await export.build_archive(
            db_session, storage, row, shared_dir=shared_dir, with_materials=False
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < len(big) // 3
    with archive:
        data = archive.read()
    assert len(data) == size
    assert zipfile.ZipFile(io.BytesIO(data)).read("materials/big.png") == big


async def test_archive_is_one_snapshot_while_files_change(
    live: Live, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Правка двух файлов, закоммиченная посреди чтения: в архиве оба файла до неё —
    и тот, что уже прочитан, и тот, что ещё нет."""
    async with live.sessionmaker() as session:
        row = await create_empty_project(session, live.owner_id)
        for number in range(6):
            await projects_service.write_text_file(
                session, writer(), row.id, f"part{number}.tex", f"старый {number}\n"
            )
    monkeypatch.setattr(projects_service, "EXPORT_BATCH_ROWS", 2)
    real = projects_service.iter_export_files

    async def edit_midway(
        session: AsyncSession, project_id: uuid.UUID, *, with_materials: bool
    ) -> AsyncIterator[list[projects_service.ExportEntry]]:
        first = True
        async for batch in real(session, project_id, with_materials=with_materials):
            yield batch
            if first:
                first = False
                async with live.sessionmaker() as other:
                    for path in ("part0.tex", "part5.tex"):
                        await other.execute(
                            update(File)
                            .where(File.project_id == project_id, File.path == path)
                            .values(content="новый\n")
                        )
                    await other.commit()

    monkeypatch.setattr(export.service, "iter_export_files", edit_midway)

    async with live.sessionmaker() as session:
        project = await session.get_one(Project, row.id)
        archive, _ = await export.build_archive(
            session, live.storage, project, shared_dir=tmp_path, with_materials=False
        )
    with archive:
        content = zipfile.ZipFile(io.BytesIO(await asyncio.to_thread(archive.read)))

    assert content.read("part0.tex") == "старый 0\n".encode()
    assert content.read("part5.tex") == "старый 5\n".encode()
    async with live.sessionmaker() as session:
        changed = await session.get_one(Project, row.id)
        assert changed is not None
