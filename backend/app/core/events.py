"""События проекта (architecture.md 9.3): журнал проекта в Redis Stream.

Сервисы пишут событие, когда изменение уже сохранено в базе (после commit): publish().
Вкладка браузера читает журнал своего проекта через SSE: сначала пропущенное после
Last-Event-ID, потом новое. Номер события — id записи Redis Stream, например
1730650000000-0. Номера растут, поэтому «после номера» — всё, что случилось позже.

Журнал хранит около STREAM_MAXLEN последних событий и живёт STREAM_TTL_S после последнего:
вкладка, которая была без связи дольше, получит только то, что осталось.

Клиент Redis — один на процесс: API открывает его в lifespan (app.state.events), воркер —
при старте (state.events). Сервисы получают его параметром, как Storage.
"""

import asyncio
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

import structlog
from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

logger = structlog.get_logger(__name__)

# Ключ журнала — <префикс>:<id проекта>. Свой префикс, а не «events»: Redis может быть общим.
STREAM_PREFIX = "blablatex:events"
# Сколько событий хранит журнал (9.3). Redis обрезает его примерно: длина бывает чуть больше.
STREAM_MAXLEN = 1000
# Журнал проекта, где сутки ничего не происходило, удаляется. Иначе в памяти Redis навсегда
# остались бы журналы всех проектов — до ~250 КБ на каждый.
STREAM_TTL_S = 24 * 60 * 60
# Сколько сохранение ждёт Redis. Изменение уже в базе: дольше задерживать ответ незачем,
# а без срока клиент redis повторяет подключение несколько секунд.
PUBLISH_TIMEOUT_S = 2.0
# После сбоя Redis события столько секунд не пишутся вовсе. Иначе каждое событие ждало бы
# PUBLISH_TIMEOUT_S: загрузка ста файлов — сто раз по столько, а ответ ИИ (B2.6) шёл бы
# кусочками раз в 2 с. Вкладки и так перезапросят данные, когда переподключатся.
PUBLISH_PAUSE_S = 10.0
# Клиент redis обрывает чтение, на которое Redis не ответил за это время.
SOCKET_TIMEOUT_S = 5.0
# Поэтому чтение с ожиданием новых событий ждёт меньше — иначе оно оборвётся ошибкой.
READ_BLOCK_MAX_MS = 4000
# Сколько событий за одно чтение: после долгого обрыва в журнале их до ~1000.
READ_COUNT = 100
# Каждая открытая вкладка держит одно соединение, пока ждёт события. У клиента redis
# по умолчанию 100 соединений на процесс: сто первая вкладка и публикации упёрлись бы в них.
# Столько же клиентов по умолчанию принимает сам Redis.
MAX_CONNECTIONS = 10_000

# Номер события — id записи Redis Stream: «миллисекунды-порядковый номер». Не больше
# 19 цифр в каждой части: такие числа Redis точно примет.
_EVENT_ID = re.compile(r"[0-9]{1,19}-[0-9]{1,19}")
# Номер «до первого события»: читать после него — значит читать журнал с начала.
FIRST_EVENT_ID = "0-0"


class EventType(StrEnum):
    """Типы событий — ровно таблица 9.3."""

    FILE_CHANGED = "file.changed"
    FILE_DELETED = "file.deleted"
    FILE_MOVED = "file.moved"
    MATERIAL_READY = "material.ready"
    BUILD_STARTED = "build.started"
    BUILD_FINISHED = "build.finished"
    RUN_STARTED = "run.started"
    RUN_DELTA = "run.delta"
    RUN_TOOL_CALL = "run.tool_call"
    RUN_TOOL_RESULT = "run.tool_result"
    RUN_FINISHED = "run.finished"
    PROJECT_LOCKED = "project.locked"
    PROJECT_UNLOCKED = "project.unlocked"


# Кто изменил файл — те же значения, что у автора changeset (раздел 5).
Author = Literal["user", "ai", "mcp", "template", "system"]


class EventData(BaseModel):
    """data события: поля и их имена в JSON — как в 9.3."""

    model_config = ConfigDict(frozen=True, validate_by_name=True, serialize_by_alias=True)


class FileChangedData(EventData):
    path: str
    version: int
    # Null только у событий, записанных до истории правок (B2.5): журнал хранит их сутки.
    changeset_id: UUID | None
    author: Author


class FileDeletedData(EventData):
    path: str
    changeset_id: UUID | None


class FileMovedData(EventData):
    from_: str = Field(alias="from")
    to: str
    changeset_id: UUID | None


class MaterialReadyData(EventData):
    path: str
    status: Literal["ready", "failed"]


class BuildStartedData(EventData):
    build_id: UUID


class BuildFinishedData(EventData):
    build_id: UUID
    status: Literal["ok", "error", "timeout"]
    pages: int | None
    errors_count: int


class RunStartedData(EventData):
    run_id: UUID
    message_id: UUID


class RunDeltaData(EventData):
    run_id: UUID
    message_id: UUID
    text: str


class RunToolCallData(EventData):
    run_id: UUID
    # id вызова инструмента у модели — строка модели, а не UUID.
    call_id: str
    tool: str
    summary: str


class RunToolResultData(EventData):
    run_id: UUID
    call_id: str
    ok: bool
    summary: str


class RunUsage(EventData):
    tokens_in: int
    tokens_out: int


class RunFinishedData(EventData):
    run_id: UUID
    status: Literal["done", "failed", "cancelled"]
    changeset_id: UUID
    usage: RunUsage


class ProjectLockedData(EventData):
    run_id: UUID


class ProjectUnlockedData(EventData):
    run_id: UUID


# Тип события → модель его data.
EVENT_DATA: dict[EventType, type[EventData]] = {
    EventType.FILE_CHANGED: FileChangedData,
    EventType.FILE_DELETED: FileDeletedData,
    EventType.FILE_MOVED: FileMovedData,
    EventType.MATERIAL_READY: MaterialReadyData,
    EventType.BUILD_STARTED: BuildStartedData,
    EventType.BUILD_FINISHED: BuildFinishedData,
    EventType.RUN_STARTED: RunStartedData,
    EventType.RUN_DELTA: RunDeltaData,
    EventType.RUN_TOOL_CALL: RunToolCallData,
    EventType.RUN_TOOL_RESULT: RunToolResultData,
    EventType.RUN_FINISHED: RunFinishedData,
    EventType.PROJECT_LOCKED: ProjectLockedData,
    EventType.PROJECT_UNLOCKED: ProjectUnlockedData,
}


def check_data(type_: EventType, data: EventData) -> None:
    """data должна быть моделью своего типа события: иначе вкладка получит не те поля."""
    expected = EVENT_DATA[type_]
    if not isinstance(data, expected):
        raise TypeError(f"У события {type_} data — {expected.__name__}, а не {type(data).__name__}")


def is_event_id(value: str) -> bool:
    """Похоже ли значение на номер события — например, из заголовка Last-Event-ID."""
    return _EVENT_ID.fullmatch(value) is not None


@dataclass(frozen=True)
class StoredEvent:
    """Событие из журнала: data — уже готовый JSON, его так и отдают вкладке."""

    id: str
    type: str
    data: str


class EventPublisher(Protocol):
    """Что нужно сервисам: только записать событие. В тестах — tests/fake_events.py."""

    async def publish(self, project_id: UUID, type_: EventType, data: EventData) -> str | None: ...


class EventBus:
    """Журналы событий проектов в Redis Streams."""

    def __init__(self, redis: Redis, *, prefix: str = STREAM_PREFIX) -> None:
        self.redis = redis
        self.prefix = prefix
        # До этого момента (time.monotonic) события не пишутся: Redis недавно был недоступен.
        self._paused_until = 0.0

    @classmethod
    def from_settings(cls, settings: Settings, *, prefix: str = STREAM_PREFIX) -> Self:
        """Клиент по REDIS_URL. Подключение открывается при первой команде, а не здесь:
        API и воркер запускаются и без Redis."""
        redis = Redis.from_url(
            settings.redis_base_url,
            decode_responses=True,
            socket_timeout=SOCKET_TIMEOUT_S,
            max_connections=MAX_CONNECTIONS,
        )
        return cls(redis, prefix=prefix)

    async def close(self) -> None:
        """Закрывает соединения с Redis."""
        await self.redis.aclose()

    def stream_key(self, project_id: UUID) -> str:
        return f"{self.prefix}:{project_id}"

    async def publish(self, project_id: UUID, type_: EventType, data: EventData) -> str | None:
        """Пишет событие в журнал проекта и возвращает его номер.

        Вызывается, когда изменение уже сохранено в базе. Поэтому сбой Redis — не ошибка
        запроса: изменение остаётся, событие теряется, в лог — предупреждение. None —
        событие не записано. Вкладки увидят изменение, когда снова запросят данные.
        После сбоя PUBLISH_PAUSE_S секунд события сразу возвращают None, не дожидаясь Redis.
        """
        check_data(type_, data)
        if time.monotonic() < self._paused_until:
            return None
        key = self.stream_key(project_id)
        fields = {"type": type_.value, "data": data.model_dump_json()}
        try:
            async with asyncio.timeout(PUBLISH_TIMEOUT_S):
                # Обе команды — за один обмен с Redis. Без транзакции: если срок не продлится,
                # его продлит следующее событие.
                async with self.redis.pipeline(transaction=False) as pipe:
                    pipe.xadd(key, fields, maxlen=STREAM_MAXLEN, approximate=True)
                    pipe.expire(key, STREAM_TTL_S)
                    event_id, _ = await pipe.execute()
        except (RedisError, TimeoutError) as error:
            self._paused_until = time.monotonic() + PUBLISH_PAUSE_S
            # Без data: в ней пути файлов пользователя.
            logger.warning(
                "event_publish_failed",
                project_id=str(project_id),
                type=type_.value,
                reason=repr(error),
                paused_s=PUBLISH_PAUSE_S,
            )
            return None
        return str(event_id)

    async def last_id(self, project_id: UUID) -> str:
        """Номер последнего события в журнале или FIRST_EVENT_ID, если событий нет.

        Вкладка без Last-Event-ID читает журнал после этого номера — то есть только новое.
        Redis недоступен — RedisError.
        """
        entries = await self.redis.xrevrange(self.stream_key(project_id), count=1)
        if not entries:
            return FIRST_EVENT_ID
        last: str = entries[0][0]
        return last

    async def read(
        self,
        project_id: UUID,
        after: str,
        *,
        block_ms: int | None = None,
        count: int = READ_COUNT,
    ) -> list[StoredEvent]:
        """События журнала после номера after — по порядку, не больше count.

        Если таких нет, ждёт новые до block_ms миллисекунд (не больше READ_BLOCK_MAX_MS);
        None — не ждать. События, которые Redis уже убрал из журнала, не вернутся:
        чтение начнётся с самого старого из оставшихся. Redis недоступен — RedisError.
        """
        if block_ms is not None and not 0 < block_ms <= READ_BLOCK_MAX_MS:
            # 0 у Redis — ждать бесконечно, а клиент оборвёт чтение через SOCKET_TIMEOUT_S.
            raise ValueError(f"block_ms — от 1 до {READ_BLOCK_MAX_MS}")
        response = await self.redis.xread(
            {self.stream_key(project_id): after}, count=count, block=block_ms
        )
        if not response:
            return []
        _, entries = response[0]
        return [
            StoredEvent(id=entry_id, type=fields["type"], data=fields["data"])
            for entry_id, fields in entries
        ]


def get_events(request: Request) -> EventBus:
    """Журнал событий приложения; его открывает lifespan из create_app()."""
    events: EventBus | None = getattr(request.app.state, "events", None)
    if events is None:
        raise RuntimeError(
            "Нет клиента событий: lifespan приложения не запущен. В тестах — фикстура app."
        )
    return events


EventsDep = Annotated[EventBus, Depends(get_events)]
