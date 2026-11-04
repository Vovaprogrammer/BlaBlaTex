"""История правок (architecture.md 5): changesets, ревизии с прежним видом файлов
и сквозные версии. Склейка автосохранений — test_coalescing.py, diff и откат —
test_changesets_api.py."""

import asyncio
import os
import uuid
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import BACKEND_DIR, Settings
from app.core.errors import AppError
from app.modules.auth import service as auth_service
from app.modules.projects import service as projects_service
from app.modules.projects.history import Writer
from app.modules.projects.models import Changeset, File, FileRevision, Project
from tests.fake_events import FakeEvents
from tests.file_samples import PNG
from tests.helpers import create_empty_project, drop_database, writer

# Any — проект как JSON из ответа API.
Json = dict[str, Any]
# Миграция перед историей правок и сама она.
BEFORE_HISTORY = "9c047b0fdac2"
HISTORY = "e1dd3a6bacb2"


async def changesets_of(session: AsyncSession, project_id: uuid.UUID) -> list[Changeset]:
    result = await session.scalars(
        select(Changeset).where(Changeset.project_id == project_id).order_by(Changeset.created_at)
    )
    return list(result)


async def revisions_of(session: AsyncSession, project_id: uuid.UUID) -> list[FileRevision]:
    result = await session.scalars(
        select(FileRevision)
        .join(Changeset, Changeset.id == FileRevision.changeset_id)
        .where(Changeset.project_id == project_id)
        .order_by(FileRevision.id)
    )
    return list(result)


async def revisions_in(
    session: AsyncSession, project_id: uuid.UUID, changeset_id: uuid.UUID
) -> list[FileRevision]:
    return [r for r in await revisions_of(session, project_id) if r.changeset_id == changeset_id]


async def file_id(session: AsyncSession, project_id: uuid.UUID, path: str) -> uuid.UUID:
    found = await session.scalar(
        select(File.id).where(File.project_id == project_id, File.path == path)
    )
    assert found is not None
    return found


@pytest.fixture
async def owner(db_session: AsyncSession) -> uuid.UUID:
    user, _ = await auth_service.register(db_session, "ivanov@example.com", "password1")
    return user.id


@pytest.fixture
async def pid(db_session: AsyncSession, owner: uuid.UUID) -> uuid.UUID:
    project = await create_empty_project(db_session, owner)
    return project.id


async def test_project_from_template_is_one_template_changeset(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    project_id = uuid.UUID(project["id"])

    [changeset] = await changesets_of(db_session, project_id)
    revisions = await revisions_of(db_session, project_id)
    files = list(await db_session.scalars(select(File).where(File.project_id == project_id)))

    assert changeset.author == "template"
    # Каждый файл и папка шаблона — новые: до changeset их не было.
    assert {revision.file_id for revision in revisions} == {file.id for file in files}
    assert {(revision.path, revision.kind) for revision in revisions} == {(None, None)}
    # Версии сквозные: у каждого файла своя, счётчик проекта — на самой большой.
    texts = [file.version for file in files if file.kind == "text"]
    assert len(set(texts)) == len(texts)
    counter = select(Project.last_file_version).where(Project.id == project_id)
    assert await db_session.scalar(counter) == max(texts)


async def test_template_changeset_is_on_behalf_of_owner(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    me = (await user_client.get("/api/v1/auth/me")).json()["user"]["id"]

    [changeset] = await changesets_of(db_session, uuid.UUID(project["id"]))

    assert changeset.author_user_id == uuid.UUID(me)


async def test_write_keeps_previous_text_and_new_file_has_no_past(
    db_session: AsyncSession, pid: uuid.UUID, owner: uuid.UUID
) -> None:
    await projects_service.write_text_file(db_session, writer(user_id=owner), pid, "a.tex", "v1")
    await projects_service.write_text_file(db_session, writer(user_id=owner), pid, "a.tex", "v2")

    created, updated = await revisions_of(db_session, pid)
    first, second = await changesets_of(db_session, pid)
    a = await file_id(db_session, pid, "a.tex")
    assert (created.changeset_id, created.file_id, created.path) == (first.id, a, None)
    assert (updated.changeset_id, updated.path, updated.kind) == (second.id, "a.tex", "text")
    assert (updated.content, updated.size, updated.mime) == ("v1", 2, "text/plain")
    assert (first.author, first.author_user_id) == ("user", owner)


async def test_new_folders_above_file_are_recorded(
    db_session: AsyncSession, pid: uuid.UUID
) -> None:
    await projects_service.write_text_file(db_session, writer(), pid, "a/b/c.tex", "x")

    revisions = await revisions_of(db_session, pid)
    ids = {await file_id(db_session, pid, path) for path in ("a", "a/b", "a/b/c.tex")}
    assert {revision.file_id for revision in revisions} == ids
    assert len(await changesets_of(db_session, pid)) == 1


async def test_move_of_folder_keeps_old_paths_of_everything_inside(
    db_session: AsyncSession, pid: uuid.UUID
) -> None:
    await projects_service.write_text_file(db_session, writer(), pid, "s/a.tex", "A")
    await projects_service.write_text_file(db_session, writer(), pid, "s/in/b.tex", "B")

    await projects_service.move_path(db_session, writer(), pid, "s", "parts/s")

    move = (await changesets_of(db_session, pid))[-1]
    before = {
        revision.path: revision.content
        for revision in await revisions_of(db_session, pid)
        if revision.changeset_id == move.id
    }
    # Прежние пути папки и всего в ней; новая папка parts — новая, без прошлого.
    assert before == {"s": None, "s/a.tex": "A", "s/in": None, "s/in/b.tex": "B", None: None}


async def test_deleted_folder_stays_in_history(db_session: AsyncSession, pid: uuid.UUID) -> None:
    await projects_service.write_text_file(db_session, writer(), pid, "s/a.tex", "A")

    await projects_service.delete_path(db_session, writer(), pid, "s")

    removal = (await changesets_of(db_session, pid))[-1]
    kept = [
        (revision.path, revision.kind, revision.content)
        for revision in await revisions_of(db_session, pid)
        if revision.changeset_id == removal.id
    ]
    assert sorted(kept, key=str) == [("s", "folder", None), ("s/a.tex", "text", "A")]


async def test_replaced_picture_keeps_reference_to_old_blob(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    url = f"/api/v1/projects/{project['id']}/upload"
    other = PNG + b"\x00"
    await user_client.post(url, files=[("files", ("plot.png", PNG))])

    await user_client.post(url, files=[("files", ("plot.png", other))])

    last = (await revisions_of(db_session, uuid.UUID(project["id"])))[-1]
    # Картинка не копируется: ревизия ссылается на тот же blob в Storage.
    assert (last.path, last.kind, last.content) == ("plot.png", "binary", None)
    assert last.blob_sha256 is not None
    assert (last.mime, last.size) == ("image/png", len(PNG))


async def test_recreated_file_gets_new_version_and_old_etag_conflicts(
    user_client: AsyncClient, project: Json
) -> None:
    url = f"/api/v1/projects/{project['id']}/files/notes.tex"
    old = await user_client.put(url, content=b"old")
    await user_client.delete(url)
    await user_client.put(url, content=b"new")

    # Вкладка ещё держит удалённый файл и сохраняет его поверх нового.
    stale = await user_client.put(url, content=b"tab", headers={"If-Match": old.headers["etag"]})

    assert stale.status_code == 412
    current = (await user_client.get(url)).headers["etag"]
    assert int(current.strip('"')) > int(old.headers["etag"].strip('"'))
    assert stale.json()["error"]["details"] == {"current_version": int(current.strip('"'))}


async def test_meta_rebuilt_from_profile_is_system_changeset_per_project(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    project_id = uuid.UUID(project["id"])
    meta_before = (await user_client.get(f"/api/v1/projects/{project_id}/files/meta.tex")).text
    profile = dict.fromkeys(("last_name", "first_name", "middle_name", "faculty"), "")

    await user_client.put(
        "/api/v1/profile", json=profile | {"group_name": "БВТ2401", "department": ""}
    )

    template, system = await changesets_of(db_session, project_id)
    [revision] = await revisions_in(db_session, project_id, system.id)
    assert (template.author, system.author) == ("template", "system")
    assert (revision.path, revision.content) == ("meta.tex", meta_before)


async def test_failed_write_leaves_no_history(db_session: AsyncSession, pid: uuid.UUID) -> None:
    await projects_service.write_text_file(db_session, writer(), pid, "a.tex", "v1")

    with pytest.raises(AppError):
        await projects_service.write_text_file(
            db_session, writer(), pid, "a.tex", "v2", expected_version=999
        )

    assert len(await changesets_of(db_session, pid)) == 1
    assert len(await revisions_of(db_session, pid)) == 1


async def explicit(session: AsyncSession, project_id: uuid.UUID) -> Writer:
    """Writer с явным changeset — как у прогона ИИ (ToolContext.changeset_id)."""
    changeset = Changeset(project_id=project_id, author="ai")
    session.add(changeset)
    await session.flush()
    return Writer(FakeEvents(), "ai", None, changeset.id)


async def test_explicit_changeset_keeps_one_revision_per_file(
    db_session: AsyncSession, pid: uuid.UUID
) -> None:
    await projects_service.write_text_file(db_session, writer(), pid, "a.tex", "v1")
    ai = await explicit(db_session, pid)

    for text_ in ("v2", "v3", "v4"):
        await projects_service.write_text_file(db_session, ai, pid, "a.tex", text_)

    assert ai.changeset_id is not None
    kept = [revision.content for revision in await revisions_in(db_session, pid, ai.changeset_id)]
    # Вид файла до changeset сохранён один раз; дальше changeset пишет поверх своего.
    assert kept == ["v1"]


async def test_other_write_in_between_gives_file_a_new_revision(
    db_session: AsyncSession, pid: uuid.UUID
) -> None:
    await projects_service.write_text_file(db_session, writer(), pid, "a.tex", "v1")
    ai = await explicit(db_session, pid)

    await projects_service.write_text_file(db_session, ai, pid, "a.tex", "ai-1")
    await projects_service.write_text_file(db_session, writer(), pid, "a.tex", "user")
    await projects_service.write_text_file(db_session, ai, pid, "a.tex", "ai-2")

    kept = [
        (r.changeset_id == ai.changeset_id, r.content) for r in await revisions_of(db_session, pid)
    ]
    # Между записями ИИ файл менял студент: его правка не припишется ИИ.
    assert kept[1:] == [(True, "v1"), (False, "ai-1"), (True, "user")]


async def test_explicit_changeset_of_other_project_is_refused(
    db_session: AsyncSession, pid: uuid.UUID, owner: uuid.UUID
) -> None:
    other = await create_empty_project(db_session, owner, "ЛР 2")
    foreign = await explicit(db_session, other.id)

    with pytest.raises(ValueError, match="не из этого проекта"):
        await projects_service.write_text_file(db_session, foreign, pid, "a.tex", "x")


async def test_events_name_the_changeset(db_session: AsyncSession, pid: uuid.UUID) -> None:
    events = FakeEvents()

    await projects_service.write_text_file(db_session, writer(events), pid, "a.tex", "x")

    [changeset] = await changesets_of(db_session, pid)
    [event] = events.published
    assert event.data.model_dump()["changeset_id"] == changeset.id


# Миграция истории на базе с данными: отдельная база, миграции — до и после истории.


async def _fill_before_history(url: str) -> uuid.UUID:
    """Проект с файлами, как до истории: версии файлов считались по каждому файлу."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            user = await connection.scalar(
                text(
                    "INSERT INTO users (email, password_hash, consent_at) "
                    "VALUES ('old@example.com', 'x', now()) RETURNING id"
                )
            )
            project = await connection.scalar(
                text(
                    "INSERT INTO projects (owner_id, title, kind, template_slug, template_version, "
                    "fields, main_file, engine) VALUES (:owner, 'ЛР', 'lab', 'test-lab', 1, "
                    "'{}', 'main.tex', 'xelatex') RETURNING id"
                ),
                {"owner": user},
            )
            await connection.execute(
                text(
                    "INSERT INTO files "
                    "(project_id, path, kind, role, content, mime, size, version) VALUES "
                    "(:p, 'main.tex', 'text', 'source', 'x', 'text/plain', 1, 7), "
                    "(:p, 'goal.tex', 'text', 'source', 'y', 'text/plain', 1, 2)"
                ),
                {"p": project},
            )
        return uuid.UUID(str(project))
    finally:
        await engine.dispose()


async def _counter(url: str, project_id: uuid.UUID) -> tuple[int, int]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            last = await connection.scalar(
                text("SELECT last_file_version FROM projects WHERE id = :p"), {"p": project_id}
            )
            revisions = await connection.scalar(text("SELECT count(*) FROM file_revisions"))
            return last, revisions
    finally:
        await engine.dispose()


def test_migration_continues_versions_of_existing_files(db_settings: Settings) -> None:
    base = Settings(app_env="test")
    name = f"{base.postgres_db}_mig_{os.getpid()}"
    settings = base.model_copy(update={"postgres_db": name})
    asyncio.run(drop_database(base.database_url, name, create_again=True))
    config = Config(toml_file=BACKEND_DIR / "pyproject.toml")
    config.attributes["database_url"] = settings.database_url
    try:
        command.upgrade(config, BEFORE_HISTORY)
        project_id = asyncio.run(_fill_before_history(settings.database_url))

        command.upgrade(config, HISTORY)
        # Старые номера не меняются, счётчик — с самого большого; истории ещё нет.
        assert asyncio.run(_counter(settings.database_url, project_id)) == (7, 0)

        command.downgrade(config, BEFORE_HISTORY)
        command.upgrade(config, "head")
    finally:
        asyncio.run(drop_database(base.database_url, name, create_again=False))
