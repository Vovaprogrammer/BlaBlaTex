"""Поток событий проекта для вкладки браузера (architecture.md 9.3).

Сначала — пропущенное после Last-Event-ID, потом новые события по мере появления; пока
событий нет — раз в KEEPALIVE_INTERVAL_S комментарий keep-alive. Модуль отдаёт готовые
куски формата SSE, ответ из них собирает router.py.
"""

import time
from collections.abc import AsyncIterator
from uuid import UUID

import structlog
from redis.exceptions import RedisError

from app.core.events import READ_BLOCK_MAX_MS, EventBus, StoredEvent

logger = structlog.get_logger(__name__)

# Как часто поток без событий шлёт комментарий: прокси не закроет «молчащее» соединение,
# а сервер заметит закрытую вкладку.
KEEPALIVE_INTERVAL_S = 15.0
KEEPALIVE = b": keep-alive\n\n"


def format_event(event: StoredEvent) -> bytes:
    """Событие в формате SSE. data — JSON в одну строку: переводы строк в нём экранированы."""
    return f"id: {event.id}\nevent: {event.type}\ndata: {event.data}\n\n".encode()


async def stream_events(bus: EventBus, project_id: UUID, after: str) -> AsyncIterator[bytes]:
    """События проекта после номера after, без конца — пока вкладка не закроет соединение.

    Redis стал недоступен — поток заканчивается: вкладка переподключится со своим
    Last-Event-ID и получит пропущенное, когда Redis вернётся.
    """
    quiet_since = time.monotonic()
    while True:
        wait_s = KEEPALIVE_INTERVAL_S - (time.monotonic() - quiet_since)
        if wait_s <= 0:
            yield KEEPALIVE
            quiet_since = time.monotonic()
            continue
        # Ждём новые события, но не дольше, чем до следующего keep-alive.
        block_ms = max(1, min(READ_BLOCK_MAX_MS, int(wait_s * 1000)))
        try:
            events = await bus.read(project_id, after, block_ms=block_ms)
        except RedisError as error:
            logger.warning("events_stream_broken", project_id=str(project_id), reason=repr(error))
            return
        for event in events:
            yield format_event(event)
            after = event.id
        if events:
            quiet_since = time.monotonic()
