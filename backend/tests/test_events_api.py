"""GET /projects/{pid}/events (architecture.md 9.3): поток SSE с replay по Last-Event-ID,
keep-alive, доступ только к своему проекту. Журнал — на настоящем Redis."""

import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from structlog.testing import capture_logs

from app.core.config import Settings
from app.core.events import (
    EVENT_DATA,
    READ_BLOCK_MAX_MS,
    EventBus,
    EventType,
    FileChangedData,
    StoredEvent,
)
from app.main import create_app
from app.modules.auth import service as auth_service
from app.modules.auth.dependencies import SESSION_COOKIE
from app.modules.events import service
from app.modules.events.router import EVENTS_UNAVAILABLE_MESSAGE
from tests.helpers import CreateProject, SignUp, create_empty_project
from tests.live_builds import Live
from tests.sse_client import Message, open_stream


def changed(version: int) -> FileChangedData:
    return FileChangedData(path="main.tex", version=version, changeset_id=None, author="user")


def events_url(project_id: object) -> str:
    return f"/api/v1/projects/{project_id}/events"


def as_user(client: AsyncClient, **headers: str) -> dict[str, str]:
    """Заголовки запроса от имени того, кто вошёл в client: cookie сессии и headers."""
    return {"cookie": f"{SESSION_COOKIE}={client.cookies[SESSION_COOKIE]}", **headers}


@pytest.fixture
def sse_app(app: FastAPI, event_bus: EventBus, db_client: AsyncClient) -> FastAPI:
    """Приложение тестов, которое читает события из журнала на настоящем Redis."""
    app.state.events = event_bus
    return app


async def test_reconnect_with_last_event_id_replays_missed_events(
    sse_app: FastAPI, event_bus: EventBus, user_client: AsyncClient, project: dict[str, Any]
) -> None:
    project_id = uuid.UUID(project["id"])
    ids = [
        await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(version))
        for version in (1, 2, 3)
    ]
    headers = as_user(user_client, **{"last-event-id": str(ids[0])})

    async with open_stream(sse_app, events_url(project_id), headers) as stream:
        missed = [await stream.next_event(), await stream.next_event()]

    assert stream.status == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache"
    assert [event.id for event in missed] == ids[1:]
    assert missed[0] == Message(
        id=ids[1],
        event="file.changed",
        data={"path": "main.tex", "version": 2, "changeset_id": None, "author": "user"},
    )


async def test_stream_without_last_event_id_gives_only_new_events(
    sse_app: FastAPI, event_bus: EventBus, user_client: AsyncClient, project: dict[str, Any]
) -> None:
    project_id = uuid.UUID(project["id"])
    await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(1))

    async with open_stream(sse_app, events_url(project_id), as_user(user_client)) as stream:
        new_id = await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(2))
        event = await stream.next_event()

    assert event.id == new_id


async def test_two_tabs_get_the_same_events(
    sse_app: FastAPI, event_bus: EventBus, user_client: AsyncClient, project: dict[str, Any]
) -> None:
    project_id = uuid.UUID(project["id"])
    url, headers = events_url(project_id), as_user(user_client)

    async with (
        open_stream(sse_app, url, headers) as first,
        open_stream(sse_app, url, headers) as second,
    ):
        event_id = await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(1))

        assert (await first.next_event()).id == event_id
        assert (await second.next_event()).id == event_id


async def test_events_of_other_projects_do_not_arrive(
    sse_app: FastAPI,
    event_bus: EventBus,
    user_client: AsyncClient,
    project: dict[str, Any],
    create_project: CreateProject,
) -> None:
    other = await create_project(title="ЛР 2")
    project_id = uuid.UUID(project["id"])

    async with open_stream(sse_app, events_url(project_id), as_user(user_client)) as stream:
        await event_bus.publish(uuid.UUID(other["id"]), EventType.FILE_CHANGED, changed(1))
        own = await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(1))

        assert (await stream.next_event()).id == own


async def test_keep_alive_while_there_are_no_events(
    sse_app: FastAPI,
    user_client: AsyncClient,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "KEEPALIVE_INTERVAL_S", 0.3)
    started = time.monotonic()

    async with open_stream(sse_app, events_url(project["id"]), as_user(user_client)) as stream:
        message = await stream.next_message()

    assert message == Message(comment="keep-alive")
    assert time.monotonic() - started >= 0.25


async def test_closed_tab_stops_stream_at_once(
    sse_app: FastAPI, user_client: AsyncClient, project: dict[str, Any]
) -> None:
    async with open_stream(sse_app, events_url(project["id"]), as_user(user_client)) as stream:
        assert stream.status == 200
        closed_at = time.monotonic()

    # Поток не дожидается конца чтения Redis (до 4 с) и следующего keep-alive.
    assert stream.app_task.done()
    assert time.monotonic() - closed_at < 1


async def test_database_connection_is_returned_before_streaming(
    db_settings: Settings, event_bus: EventBus, live: Live, tmp_path: Path
) -> None:
    app = create_app(db_settings.model_copy(update={"storage_dir": tmp_path / "storage"}))
    app.state.db_sessionmaker = live.sessionmaker
    app.state.events = event_bus
    async with live.sessionmaker() as session:
        project = await create_empty_project(session, live.owner_id)
        token = auth_service.create_session(session, live.owner_id)
        await session.commit()
    engine = live.sessionmaker.kw["bind"]
    headers = {"cookie": f"{SESSION_COOKIE}={token}"}

    async with open_stream(app, events_url(project.id), headers) as stream:
        event_id = await event_bus.publish(project.id, EventType.FILE_CHANGED, changed(1))

        assert (await stream.next_event()).id == event_id
        # Поток открыт, а соединение с базой уже вернулось в пул.
        assert engine.pool.checkedout() == 0


async def test_foreign_project_is_not_found(
    user_client: AsyncClient, project: dict[str, Any], sign_up: SignUp
) -> None:
    await sign_up("petrov@example.com")

    response = await user_client.get(events_url(project["id"]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_events_need_login(db_client: AsyncClient, project: dict[str, Any]) -> None:
    db_client.cookies.clear()

    response = await db_client.get(events_url(project["id"]))

    assert response.status_code == 401


async def test_malformed_last_event_id_is_rejected(
    user_client: AsyncClient, project: dict[str, Any]
) -> None:
    response = await user_client.get(
        events_url(project["id"]), headers={"Last-Event-ID": "yesterday"}
    )

    assert response.status_code == 422
    [error] = response.json()["error"]["details"]["errors"]
    assert error["loc"] == ["header", "last-event-id"]


async def test_redis_down_on_connect_is_internal_error(
    app: FastAPI,
    event_bus: EventBus,
    user_client: AsyncClient,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(project_id: uuid.UUID) -> str:
        raise RedisConnectionError("Redis недоступен")

    monkeypatch.setattr(event_bus, "last_id", unavailable)
    app.state.events = event_bus

    response = await user_client.get(events_url(project["id"]))

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal",
        "message": EVENTS_UNAVAILABLE_MESSAGE,
        "details": {},
    }


class _BrokenBus:
    """Журнал, у которого Redis пропал посреди потока; запоминает, сколько ждали чтения."""

    def __init__(self) -> None:
        self.blocks: list[int | None] = []

    async def read(
        self, project_id: uuid.UUID, after: str, *, block_ms: int | None = None
    ) -> list[StoredEvent]:
        self.blocks.append(block_ms)
        raise RedisConnectionError("Redis недоступен")


async def test_stream_ends_when_redis_breaks() -> None:
    bus = _BrokenBus()

    with capture_logs() as logs:
        chunks = [
            chunk
            async for chunk in service.stream_events(bus, uuid.uuid4(), "0-0")  # type: ignore[arg-type]
        ]

    # Клиент переподключится со своим Last-Event-ID, когда Redis вернётся.
    assert chunks == []
    assert [log["event"] for log in logs] == ["events_stream_broken"]
    # Чтение ждёт меньше, чем клиент redis ждёт ответа (5 с).
    assert bus.blocks == [READ_BLOCK_MAX_MS]


def test_event_is_formatted_as_sse() -> None:
    event = StoredEvent(id="1-0", type="build.started", data='{"build_id": "b"}')

    assert service.format_event(event) == (
        b'id: 1-0\nevent: build.started\ndata: {"build_id": "b"}\n\n'
    )


def test_openapi_describes_every_event(app: FastAPI) -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    mapping = schemas["ProjectEvent"]["discriminator"]["mapping"]
    responses = spec["paths"]["/api/v1/projects/{pid}/events"]["get"]["responses"]

    assert responses["200"]["content"]["text/event-stream"]["itemSchema"] == {
        "$ref": "#/components/schemas/ProjectEvent"
    }
    # Ошибки — обычный JSON по 9.2, а не поток.
    assert set(responses["default"]["content"]) == {"application/json"}
    assert set(mapping) == {type_.value for type_ in EventType}
    for type_, ref in mapping.items():
        message = schemas[ref.rsplit("/", 1)[1]]
        data_model = EVENT_DATA[EventType(type_)].__name__
        assert message["properties"]["data"] == {"$ref": f"#/components/schemas/{data_model}"}
        assert set(message["required"]) == {"id", "event", "data"}
