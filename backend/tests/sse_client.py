"""Чтение бесконечного SSE-ответа в тестах.

httpx с ASGITransport отдаёт ответ, только когда приложение его закончило, а поток событий
не кончается. Здесь приложение вызывается напрямую по ASGI: тест читает ответ по кускам,
пока не получит нужное, а на выходе «закрывает вкладку» — приложение получает
http.disconnect, как от uvicorn.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.types import Message as AsgiMessage
from starlette.types import Scope

# Сколько тест ждёт следующий кусок ответа.
TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Message:
    """Сообщение потока: событие или комментарий (у комментария — только comment)."""

    id: str | None = None
    event: str | None = None
    # Any: data события — JSON любого из 13 типов 9.3.
    data: Any = None
    comment: str | None = None


@dataclass
class EventStream:
    status: int
    headers: dict[str, str]
    chunks: asyncio.Queue[bytes | None]
    app_task: asyncio.Task[None]
    buffer: str = ""

    async def next_message(self, timeout_s: float = TIMEOUT_S) -> Message:
        """Следующее сообщение потока; поток закончился — AssertionError."""
        async with asyncio.timeout(timeout_s):
            while "\n\n" not in self.buffer:
                chunk = await self.chunks.get()
                assert chunk is not None, f"Поток закончился, в нём осталось: {self.buffer!r}"
                self.buffer += chunk.decode()
        block, self.buffer = self.buffer.split("\n\n", 1)
        return _parse(block)

    async def next_event(self, timeout_s: float = TIMEOUT_S) -> Message:
        """Следующее событие, комментарии keep-alive пропускаются."""
        while True:
            message = await self.next_message(timeout_s)
            if message.comment is None:
                return message

    async def body(self, timeout_s: float = TIMEOUT_S) -> str:
        """Весь ответ до конца — для ответов, которые заканчиваются (ошибки)."""
        async with asyncio.timeout(timeout_s):
            while (chunk := await self.chunks.get()) is not None:
                self.buffer += chunk.decode()
        return self.buffer


def _parse(block: str) -> Message:
    fields: dict[str, str] = {}
    comment = None
    for line in block.split("\n"):
        if line.startswith(":"):
            comment = line[1:].strip()
            continue
        name, _, value = line.partition(": ")
        fields[name] = value
    data = json.loads(fields["data"]) if "data" in fields else None
    return Message(id=fields.get("id"), event=fields.get("event"), data=data, comment=comment)


@asynccontextmanager
async def open_stream(
    app: FastAPI, path: str, headers: Mapping[str, str] | None = None
) -> AsyncIterator[EventStream]:
    """GET path к приложению; внутри блока — ответ, после блока клиент отключён, а
    приложение должно закончить ответ (иначе тест упадёт по таймауту)."""
    scope: Scope = {
        "type": "http",
        # Как у uvicorn: Starlette сама слушает отключение клиента.
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in {"host": "test", **(headers or {})}.items()
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    disconnected = asyncio.Event()
    request_sent = False
    started: asyncio.Future[AsgiMessage] = asyncio.get_running_loop().create_future()
    chunks: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def receive() -> AsgiMessage:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: AsgiMessage) -> None:
        if message["type"] == "http.response.start":
            started.set_result(message)
        elif message["type"] == "http.response.body":
            chunks.put_nowait(message.get("body", b""))
            if not message.get("more_body", False):
                chunks.put_nowait(None)

    task = asyncio.create_task(app(scope, receive, send))
    try:
        async with asyncio.timeout(TIMEOUT_S):
            done, _ = await asyncio.wait({task, started}, return_when=asyncio.FIRST_COMPLETED)
        if started not in done:
            # Приложение упало, не начав ответ: показать его ошибку.
            await task
        start = started.result()
        response_headers = {
            name.decode("latin-1"): value.decode("latin-1") for name, value in start["headers"]
        }
        yield EventStream(start["status"], response_headers, chunks, task)
    except BaseException:
        # Тест уже упал: закрыть поток, но показать его ошибку, а не ошибку приложения.
        disconnected.set()
        await asyncio.wait({task}, timeout=TIMEOUT_S)
        task.cancel()
        raise
    disconnected.set()
    async with asyncio.timeout(TIMEOUT_S):
        await task
