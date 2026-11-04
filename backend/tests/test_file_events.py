"""События о файлах (architecture.md 9.3): после сохранения в базе другие вкладки узнают
об изменении из журнала проекта — с changeset, в который попала правка, и его автором."""

import json
import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import FIRST_EVENT_ID, Author, EventBus, EventType
from app.modules.auth.models import User
from app.modules.projects.models import Changeset
from tests.fake_events import FakeEvents
from tests.helpers import STUDENT_EMAIL, CreateProject

# Any — проект и data события как JSON.
Project = dict[str, Any]
Seen = tuple[EventType, dict[str, Any]]


def project_url(project: Project) -> str:
    return f"/api/v1/projects/{project['id']}"


def changed(path: str, version: int, author: Author = "user") -> Seen:
    return EventType.FILE_CHANGED, {"path": path, "version": version, "author": author}


def seen(events: FakeEvents, project: Project | None = None) -> list[Seen]:
    """Что получат вкладки (проекта project), без changeset_id: его проверяют отдельно."""
    return [
        (event.type, event.data.model_dump(mode="json", exclude={"changeset_id"}))
        for event in events.published
        if project is None or event.project_id == uuid.UUID(project["id"])
    ]


async def put(client: AsyncClient, project: Project, path: str, text: str, **headers: str) -> int:
    response = await client.put(
        f"{project_url(project)}/files/{path}", content=text.encode(), headers=headers
    )
    return response.status_code


async def save(client: AsyncClient, project: Project, path: str, text: str, **headers: str) -> int:
    """Сохраняет файл и возвращает его новую версию."""
    response = await client.put(
        f"{project_url(project)}/files/{path}", content=text.encode(), headers=headers
    )
    assert response.status_code in (200, 201), response.text
    version: int = response.json()["version"]
    return version


async def meta_version(client: AsyncClient, project: Project) -> int:
    response = await client.get(f"{project_url(project)}/files/meta.tex")
    return int(response.headers["etag"].strip('"'))


async def test_saved_file_is_announced_after_each_save(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    # Проект из шаблона создаётся без событий: его ещё никто не смотрит.
    assert events.published == []

    first = await save(user_client, project, "notes.tex", "Черновик")
    second = await save(user_client, project, "notes.tex", "Чистовик", **{"If-Match": f'"{first}"'})

    assert second > first
    assert seen(events) == [changed("notes.tex", first), changed("notes.tex", second)]


async def test_failed_save_is_not_announced(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    await put(user_client, project, "notes.tex", "Черновик")
    events.published.clear()

    # Версия устарела — в базе ничего не изменилось, и событию взяться неоткуда.
    assert await put(user_client, project, "notes.tex", "Правка", **{"If-Match": '"999"'}) == 412
    assert await put(user_client, project, "meta.tex", "Правка") == 403

    assert events.published == []


async def test_uploaded_files_are_announced_in_request_order(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    parts = [("files", ("b.txt", b"two")), ("files", ("a.txt", b"one"))]

    response = await user_client.post(
        f"{project_url(project)}/upload", files=parts, data={"dir": "materials"}
    )

    assert response.status_code == 200
    b, a = (item["version"] for item in response.json()["items"])
    assert seen(events) == [changed("materials/b.txt", b), changed("materials/a.txt", a)]


async def test_new_folder_is_announced(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    response = await user_client.post(f"{project_url(project)}/folders", json={"path": "screens"})

    assert response.status_code == 201
    assert seen(events) == [changed("screens", response.json()["version"])]


async def test_move_and_delete_send_one_event_even_for_folder(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    await put(user_client, project, "parts/one.tex", "1")
    await put(user_client, project, "parts/two.tex", "2")
    events.published.clear()
    move_url = f"{project_url(project)}/move"

    same = await user_client.post(move_url, json={"from": "parts", "to": "parts"})
    moved = await user_client.post(move_url, json={"from": "parts", "to": "chapters"})
    deleted = await user_client.delete(f"{project_url(project)}/files/chapters")

    assert (same.status_code, moved.status_code, deleted.status_code) == (200, 200, 204)
    # Перенос на то же место ничего не меняет — события нет. Вложенные файлы переехали
    # и удалились вместе с папкой: вкладка поймёт это по пути папки.
    assert seen(events) == [
        (EventType.FILE_MOVED, {"from": "parts", "to": "chapters"}),
        (EventType.FILE_DELETED, {"path": "chapters"}),
    ]


async def test_meta_rebuilt_from_project_fields_is_announced_by_system(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    fields = {"lab_number": 2, "lab_title": "Деревья"}

    renamed = await user_client.patch(project_url(project), json={"title": "ЛР 2"})
    refilled = await user_client.patch(project_url(project), json={"fields": fields})

    assert (renamed.status_code, refilled.status_code) == (200, 200)
    # Новое название meta.tex не меняет; новые поля — меняют, и меняет его сервер.
    version = await meta_version(user_client, project)
    assert seen(events) == [changed("meta.tex", version, author="system")]


async def test_meta_rebuilt_from_profile_is_announced_in_every_project(
    user_client: AsyncClient, project: Project, create_project: CreateProject, events: FakeEvents
) -> None:
    other = await create_project(title="ЛР 2")
    profile = {
        "last_name": "Иванов",
        "first_name": "Иван",
        "middle_name": "",
        "group_name": "БВТ2401",
        "faculty": "",
        "department": "",
    }

    first = await user_client.put("/api/v1/profile", json=profile)
    again = await user_client.put("/api/v1/profile", json=profile)

    assert (first.status_code, again.status_code) == (200, 200)
    # Тот же профиль второй раз meta.tex не меняет — событий больше нет.
    for each in (project, other):
        version = await meta_version(user_client, each)
        assert seen(events, each) == [changed("meta.tex", version, author="system")]
    assert len(events.published) == 2


async def test_events_carry_changeset_and_author_of_the_write(
    user_client: AsyncClient, project: Project, events: FakeEvents, db_session: AsyncSession
) -> None:
    await put(user_client, project, "parts/one.tex", "1")
    await user_client.post(f"{project_url(project)}/move", json={"from": "parts", "to": "ch"})
    await user_client.delete(f"{project_url(project)}/files/ch")
    fields = {"lab_number": 5, "lab_title": "Графы"}
    await user_client.patch(project_url(project), json={"fields": fields})

    student = await db_session.scalar(select(User.id).where(User.email == STUDENT_EMAIL))
    changesets = {
        changeset.id: changeset
        for changeset in await db_session.scalars(
            select(Changeset).where(Changeset.project_id == uuid.UUID(project["id"]))
        )
    }
    written = []
    for event in events.published:
        data = event.data.model_dump()
        changeset = changesets[data["changeset_id"]]
        # Правки — от имени студента: и его собственные, и meta.tex по его полям.
        assert changeset.author_user_id == student
        assert data.get("author", changeset.author) == changeset.author
        written.append(changeset.author)
    assert written == ["user", "user", "user", "system"]


async def test_other_tab_finds_saved_file_in_project_journal(
    app: FastAPI, event_bus: EventBus, user_client: AsyncClient, project: Project
) -> None:
    app.state.events = event_bus
    project_id = uuid.UUID(project["id"])

    version = await save(user_client, project, "notes.tex", "Черновик")

    # Так вторая вкладка получает событие через GET /events (её поток читает этот журнал).
    [event] = await event_bus.read(project_id, FIRST_EVENT_ID)
    assert event.type == "file.changed"
    data = json.loads(event.data)
    assert uuid.UUID(data.pop("changeset_id"))
    assert data == {"path": "notes.tex", "version": version, "author": "user"}
