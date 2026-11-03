"""События о файлах (architecture.md 9.3): после сохранения в базе другие вкладки узнают
об изменении из журнала проекта. До changesets (B2.5) changeset_id — null."""

import json
import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from app.core.events import (
    FIRST_EVENT_ID,
    Author,
    EventBus,
    EventType,
    FileChangedData,
    FileDeletedData,
    FileMovedData,
)
from tests.fake_events import FakeEvents, PublishedEvent
from tests.helpers import CreateProject

# Any — проект как JSON из ответа API.
Project = dict[str, Any]


def project_url(project: Project) -> str:
    return f"/api/v1/projects/{project['id']}"


def changed(project: Project, path: str, version: int, author: Author = "user") -> PublishedEvent:
    data = FileChangedData(path=path, version=version, changeset_id=None, author=author)
    return PublishedEvent(uuid.UUID(project["id"]), EventType.FILE_CHANGED, data)


async def put(client: AsyncClient, project: Project, path: str, text: str, **headers: str) -> int:
    response = await client.put(
        f"{project_url(project)}/files/{path}", content=text.encode(), headers=headers
    )
    return response.status_code


async def test_saved_file_is_announced_after_each_save(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    # Проект из шаблона создаётся без событий: его ещё никто не смотрит.
    assert events.published == []

    assert await put(user_client, project, "notes.tex", "Черновик") == 201
    assert await put(user_client, project, "notes.tex", "Чистовик", **{"If-Match": '"1"'}) == 200

    assert events.published == [
        changed(project, "notes.tex", 1),
        changed(project, "notes.tex", 2),
    ]


async def test_failed_save_is_not_announced(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    await put(user_client, project, "notes.tex", "Черновик")
    events.published.clear()

    # Версия устарела — в базе ничего не изменилось, и событию взяться неоткуда.
    assert await put(user_client, project, "notes.tex", "Правка", **{"If-Match": '"7"'}) == 412
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
    assert events.published == [
        changed(project, "materials/b.txt", 1),
        changed(project, "materials/a.txt", 1),
    ]


async def test_new_folder_is_announced(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    response = await user_client.post(f"{project_url(project)}/folders", json={"path": "screens"})

    assert response.status_code == 201
    assert events.published == [changed(project, "screens", 1)]


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
    project_id = uuid.UUID(project["id"])
    # Перенос на то же место ничего не меняет — события нет. Вложенные файлы переехали
    # и удалились вместе с папкой: вкладка поймёт это по пути папки.
    assert events.published == [
        PublishedEvent(
            project_id,
            EventType.FILE_MOVED,
            FileMovedData(from_="parts", to="chapters", changeset_id=None),
        ),
        PublishedEvent(
            project_id, EventType.FILE_DELETED, FileDeletedData(path="chapters", changeset_id=None)
        ),
    ]


async def test_meta_rebuilt_from_project_fields_is_announced_by_system(
    user_client: AsyncClient, project: Project, events: FakeEvents
) -> None:
    fields = {"lab_number": 2, "lab_title": "Деревья"}

    renamed = await user_client.patch(project_url(project), json={"title": "ЛР 2"})
    refilled = await user_client.patch(project_url(project), json={"fields": fields})

    assert (renamed.status_code, refilled.status_code) == (200, 200)
    # Новое название meta.tex не меняет; новые поля — меняют, и меняет его сервер.
    assert events.published == [changed(project, "meta.tex", 2, author="system")]


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
    assert sorted(events.published, key=lambda event: str(event.project_id)) == sorted(
        [changed(project, "meta.tex", 2, author="system"), changed(other, "meta.tex", 2, "system")],
        key=lambda event: str(event.project_id),
    )


async def test_other_tab_finds_saved_file_in_project_journal(
    app: FastAPI, event_bus: EventBus, user_client: AsyncClient, project: Project
) -> None:
    app.state.events = event_bus
    project_id = uuid.UUID(project["id"])

    await put(user_client, project, "notes.tex", "Черновик")

    # Так вторая вкладка получает событие через GET /events (её поток читает этот журнал).
    [event] = await event_bus.read(project_id, FIRST_EVENT_ID)
    assert event.type == "file.changed"
    assert json.loads(event.data) == {
        "path": "notes.tex",
        "version": 1,
        "changeset_id": None,
        "author": "user",
    }
