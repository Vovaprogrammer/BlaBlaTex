"""Журнал событий проекта (architecture.md 9.3): запись, чтение после номера (replay),
ожидание новых, обрезка и срок жизни журнала, сбой Redis. Журнал — на настоящем Redis."""

import asyncio
import json
import socket
import time
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, Request
from redis.exceptions import ConnectionError as RedisConnectionError
from structlog.testing import capture_logs

from app.core import events as events_module
from app.core.config import Settings
from app.core.events import (
    EVENT_DATA,
    FIRST_EVENT_ID,
    MAX_CONNECTIONS,
    PUBLISH_TIMEOUT_S,
    READ_BLOCK_MAX_MS,
    SOCKET_TIMEOUT_S,
    STREAM_MAXLEN,
    STREAM_TTL_S,
    BuildStartedData,
    EventBus,
    EventType,
    FileChangedData,
    FileDeletedData,
    FileMovedData,
    RunUsage,
    get_events,
    is_event_id,
)
from tests.fake_events import FakeEvents

# Таблица 9.3: тип события → поля data.
CONTRACT = {
    "file.changed": {"path", "version", "changeset_id", "author"},
    "file.deleted": {"path", "changeset_id"},
    "file.moved": {"from", "to", "changeset_id"},
    "material.ready": {"path", "status"},
    "build.started": {"build_id"},
    "build.finished": {"build_id", "status", "pages", "errors_count"},
    "run.started": {"run_id", "message_id"},
    "run.delta": {"run_id", "message_id", "seq", "text"},
    "run.tool_call": {"run_id", "call_id", "seq", "tool", "summary"},
    "run.tool_result": {"run_id", "call_id", "seq", "ok", "summary"},
    "run.finished": {"run_id", "status", "changeset_id", "usage"},
    "project.locked": {"run_id"},
    "project.unlocked": {"run_id"},
}


def changed(version: int = 1) -> FileChangedData:
    return FileChangedData(path="main.tex", version=version, changeset_id=None, author="user")


@pytest.fixture
async def offline_bus() -> AsyncIterator[EventBus]:
    """Журнал, у которого нет Redis: по адресу никто не слушает."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    bus = EventBus.from_settings(Settings(_env_file=None, redis_url=f"redis://127.0.0.1:{port}/0"))
    yield bus
    await bus.close()


def test_event_types_and_fields_follow_contract() -> None:
    assert {type_.value for type_ in EventType} == set(CONTRACT)
    for type_, model in EVENT_DATA.items():
        fields = {field.alias or name for name, field in model.model_fields.items()}
        assert fields == CONTRACT[type_], type_
    assert set(RunUsage.model_fields) == {"tokens_in", "tokens_out"}


async def test_published_event_is_read_with_type_and_json_data(event_bus: EventBus) -> None:
    project_id = uuid.uuid4()
    moved = FileMovedData(from_="a.tex", to="b/a.tex", changeset_id=None)

    event_id = await event_bus.publish(project_id, EventType.FILE_MOVED, moved)

    [event] = await event_bus.read(project_id, FIRST_EVENT_ID)
    assert event_id is not None and is_event_id(event_id)
    assert event.id == event_id
    assert event.type == "file.moved"
    # Имена полей — как в 9.3: from, а не from_.
    assert json.loads(event.data) == {"from": "a.tex", "to": "b/a.tex", "changeset_id": None}


async def test_replay_returns_events_after_last_seen_in_order(event_bus: EventBus) -> None:
    project_id = uuid.uuid4()
    ids = [
        await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(version))
        for version in (1, 2, 3)
    ]
    assert None not in ids

    missed = await event_bus.read(project_id, str(ids[0]))

    assert [event.id for event in missed] == ids[1:]
    assert [json.loads(event.data)["version"] for event in missed] == [2, 3]
    assert await event_bus.read(project_id, str(ids[-1])) == []


async def test_projects_have_separate_journals(event_bus: EventBus) -> None:
    project_id, other_id = uuid.uuid4(), uuid.uuid4()

    await event_bus.publish(
        project_id, EventType.BUILD_STARTED, BuildStartedData(build_id=uuid.uuid4())
    )

    assert await event_bus.read(other_id, FIRST_EVENT_ID) == []


async def test_reading_after_last_id_gives_only_new_events(event_bus: EventBus) -> None:
    project_id = uuid.uuid4()
    assert await event_bus.last_id(project_id) == FIRST_EVENT_ID
    old = await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(1))

    start = await event_bus.last_id(project_id)
    new = await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(2))

    assert start == old
    assert [event.id for event in await event_bus.read(project_id, start)] == [new]


async def test_read_waits_for_new_event(event_bus: EventBus) -> None:
    project_id = uuid.uuid4()
    start = await event_bus.last_id(project_id)
    reading = asyncio.create_task(event_bus.read(project_id, start, block_ms=READ_BLOCK_MAX_MS))
    await asyncio.sleep(0.2)

    event_id = await event_bus.publish(project_id, EventType.FILE_CHANGED, changed())

    events = await asyncio.wait_for(reading, timeout=2)
    assert [event.id for event in events] == [event_id]


async def test_read_without_new_events_returns_nothing_after_wait(event_bus: EventBus) -> None:
    started = time.monotonic()

    assert await event_bus.read(uuid.uuid4(), FIRST_EVENT_ID, block_ms=200) == []
    assert time.monotonic() - started >= 0.15


@pytest.mark.parametrize("block_ms", [0, -1, READ_BLOCK_MAX_MS + 1])
async def test_read_waits_less_than_client_read_timeout(
    offline_bus: EventBus, block_ms: int
) -> None:
    # При BLOCK 0 Redis ждёт бесконечно, а клиент оборвёт чтение через SOCKET_TIMEOUT_S.
    assert READ_BLOCK_MAX_MS < SOCKET_TIMEOUT_S * 1000
    with pytest.raises(ValueError, match="block_ms"):
        await offline_bus.read(uuid.uuid4(), FIRST_EVENT_ID, block_ms=block_ms)


async def test_journal_keeps_about_last_maxlen_events(event_bus: EventBus) -> None:
    project_id = uuid.uuid4()
    first = await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(0))
    for version in range(1, STREAM_MAXLEN + 300):
        await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(version))

    length = await event_bus.redis.xlen(event_bus.stream_key(project_id))
    # Вкладка, которая видела только первое событие, получит лишь то, что осталось.
    [oldest] = await event_bus.read(project_id, str(first), count=1)

    assert STREAM_MAXLEN <= length < STREAM_MAXLEN + 300
    assert json.loads(oldest.data)["version"] > 1


async def test_journal_lives_a_day_after_last_event(event_bus: EventBus) -> None:
    project_id = uuid.uuid4()

    await event_bus.publish(project_id, EventType.FILE_CHANGED, changed())

    ttl = await event_bus.redis.ttl(event_bus.stream_key(project_id))
    assert STREAM_TTL_S - 60 < ttl <= STREAM_TTL_S


async def test_publishing_pauses_after_redis_failure(
    event_bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = uuid.uuid4()
    monkeypatch.setattr(events_module, "PUBLISH_PAUSE_S", 0.3)
    pipeline = event_bus.redis.pipeline

    def unavailable(*args: object, **kwargs: object) -> object:
        raise RedisConnectionError("Redis недоступен")

    with capture_logs() as logs:
        monkeypatch.setattr(event_bus.redis, "pipeline", unavailable)
        assert await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(1)) is None
        monkeypatch.setattr(event_bus.redis, "pipeline", pipeline)
        # Redis уже вернулся, но пауза идёт: событие не пишется и Redis не ждёт.
        started = time.monotonic()
        assert await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(2)) is None
        assert time.monotonic() - started < 0.1
        await asyncio.sleep(0.35)
        assert await event_bus.publish(project_id, EventType.FILE_CHANGED, changed(3)) is not None

    # Предупреждение — одно на сбой, а не на каждое пропущенное событие.
    assert [log["event"] for log in logs] == ["event_publish_failed"]
    journal = await event_bus.read(project_id, FIRST_EVENT_ID)
    assert [json.loads(event.data)["version"] for event in journal] == [3]


async def test_publish_without_redis_loses_event_but_does_not_fail(offline_bus: EventBus) -> None:
    deleted = FileDeletedData(path="секрет.tex", changeset_id=None)
    started = time.monotonic()

    with capture_logs() as logs:
        event_id = await offline_bus.publish(uuid.uuid4(), EventType.FILE_DELETED, deleted)

    assert event_id is None
    # Сохранение, после которого шлётся событие, не ждёт Redis дольше срока.
    assert time.monotonic() - started < PUBLISH_TIMEOUT_S + 1
    [log] = [log for log in logs if log["event"] == "event_publish_failed"]
    assert log["type"] == "file.deleted"
    assert "секрет.tex" not in str(log)


async def test_data_must_match_event_type(offline_bus: EventBus) -> None:
    for publisher in (offline_bus, FakeEvents()):
        with pytest.raises(TypeError, match="BuildStartedData"):
            await publisher.publish(uuid.uuid4(), EventType.BUILD_STARTED, changed())


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("1730650000000-0", True),
        ("0-0", True),
        ("1730650000000", False),
        ("1730650000000-0-1", False),
        ("$", False),
        ("12345678901234567890-0", False),
        (" 1-0", False),
    ],
)
def test_event_id_format(value: str, valid: bool) -> None:
    assert is_event_id(value) is valid


async def test_client_takes_address_from_settings_and_allows_many_streams() -> None:
    bus = EventBus.from_settings(Settings(_env_file=None, redis_url="redis://redis.test:6380/2"))
    try:
        pool = bus.redis.connection_pool
        assert (pool.connection_kwargs["host"], pool.connection_kwargs["port"]) == (
            "redis.test",
            6380,
        )
        assert pool.connection_kwargs["db"] == 2
        assert pool.connection_kwargs["socket_timeout"] == SOCKET_TIMEOUT_S
        # Каждая открытая вкладка держит соединение: 100 по умолчанию на процесс мало.
        assert pool.max_connections == MAX_CONNECTIONS
    finally:
        await bus.close()


async def test_lifespan_opens_and_closes_event_bus(
    app: FastAPI, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[EventBus] = []
    close = EventBus.close

    async def spy_close(self: EventBus) -> None:
        closed.append(self)
        await close(self)

    monkeypatch.setattr(EventBus, "close", spy_close)

    async with app.router.lifespan_context(app):
        bus = get_events(Request({"type": "http", "app": app}))

        assert isinstance(bus, EventBus)
        address = urlsplit(settings.redis_base_url)
        kwargs = bus.redis.connection_pool.connection_kwargs
        # Порт Redis по умолчанию — 6379, если в REDIS_URL его нет.
        assert (kwargs["host"], kwargs["port"]) == (address.hostname, address.port or 6379)
    assert closed == [bus]


def test_get_events_without_lifespan_says_what_is_missing() -> None:
    request = Request({"type": "http", "app": FastAPI()})

    with pytest.raises(RuntimeError, match="lifespan"):
        get_events(request)
