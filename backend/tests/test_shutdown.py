"""Остановка сервера закрывает потоки событий (core/shutdown.py, architecture.md 9.3).

uvicorn при остановке ждёт открытые ответы без срока, поэтому без отметки остановки
открытая вкладка проекта не давала fastapi dev перезапуститься после правки кода.
"""

import asyncio
import signal
import socket
import sys
import time
import uuid
from pathlib import Path
from types import FrameType

import httpx
import pytest

from app.core.config import BACKEND_DIR
from app.core.shutdown import Shutdown


async def test_signal_marks_shutdown_and_reaches_previous_handler() -> None:
    calls: list[int] = []

    def previous(signum: int, frame: FrameType | None) -> None:
        calls.append(signum)

    # Как у uvicorn: свой обработчик стоит раньше, чем начинается lifespan.
    original = signal.signal(signal.SIGTERM, previous)
    try:
        shutdown = Shutdown()
        with shutdown.on_signals():
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler) and handler is not previous
            handler(signal.SIGTERM, None)
            await asyncio.sleep(0)
            assert shutdown.is_set()
            # Сигнал дошёл и до uvicorn: тот начинает обычную остановку.
            assert calls == [signal.SIGTERM]
        assert signal.getsignal(signal.SIGTERM) is previous
    finally:
        signal.signal(signal.SIGTERM, original)


async def test_signal_nobody_handles_is_left_alone() -> None:
    original = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        with Shutdown().on_signals():
            # Без uvicorn процесс по такому сигналу и так остановится сразу.
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
    finally:
        signal.signal(signal.SIGTERM, original)


async def test_new_lifespan_starts_without_old_stop_mark() -> None:
    shutdown = Shutdown()
    shutdown.set()

    # Второй lifespan того же приложения: прошлая остановка новые потоки не закрывает.
    with shutdown.on_signals():
        assert not shutdown.is_set()


async def test_cancel_while_work_stops_is_not_swallowed() -> None:
    shutdown = Shutdown()

    async def slow_to_stop() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.1)
            raise

    caller = asyncio.create_task(shutdown.unless_stopped(slow_to_stop()))
    await asyncio.sleep(0)
    shutdown.set()
    # Сервер останавливается, и чтение отменяется; тут вкладку закрыли — и нас отменили.
    await asyncio.sleep(0.02)
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller


async def test_work_result_is_returned_until_shutdown() -> None:
    shutdown = Shutdown()

    assert await shutdown.unless_stopped(asyncio.sleep(0, result="готово")) == "готово"
    shutdown.set()
    assert await shutdown.unless_stopped(asyncio.sleep(10)) is None


# Настоящее приложение под настоящим uvicorn. Подменены только проект (без базы и входа)
# и журнал событий (без Redis): событий нет, чтение ждёт их, сколько разрешено. По строке
# в stdin процесс получает SIGINT — так fastapi dev на Windows перезапускает процесс, а на
# Linux так останавливает Ctrl+C.
_SERVER = r"""
import asyncio
import signal
import sys
import threading
from types import SimpleNamespace
from uuid import UUID

import uvicorn

from app.core.config import Settings
from app.core.events import get_events
from app.main import create_app
from app.modules.projects.dependencies import get_owned_project


class QuietBus:
    async def last_id(self, project_id):
        return "0-0"

    async def read(self, project_id, after, *, block_ms=None):
        await asyncio.sleep((block_ms or 0) / 1000)
        return []


app = create_app(Settings(app_env="test"))
app.dependency_overrides[get_owned_project] = lambda: SimpleNamespace(id=UUID(sys.argv[2]))
app.dependency_overrides[get_events] = QuietBus


def stop_on_request():
    sys.stdin.readline()
    signal.raise_signal(signal.SIGINT)


threading.Thread(target=stop_on_request, daemon=True).start()
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _printed(output: Path) -> str:
    """Что вывел сервер — в сообщение упавшей проверки."""
    return output.read_text(errors="replace")


async def _wait_until_up(
    client: httpx.AsyncClient, server: asyncio.subprocess.Process, output: Path
) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        assert server.returncode is None, f"сервер не запустился:\n{_printed(output)}"
        try:
            if (await client.get("/api/v1/health", timeout=1)).status_code == 200:
                return
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.1)
    raise AssertionError(f"сервер не ответил за 30 с:\n{_printed(output)}")


async def test_open_event_stream_closes_when_server_stops(tmp_path: Path) -> None:
    port, project_id = _free_port(), uuid.uuid4()
    output = tmp_path / "server.log"
    with output.open("wb") as log:
        server = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _SERVER,
            str(port),
            str(project_id),
            cwd=BACKEND_DIR,
            stdin=asyncio.subprocess.PIPE,
            stdout=log,
            stderr=log,
        )
    assert server.stdin is not None
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            await _wait_until_up(client, server, output)
            # Без отметки остановки поток не кончился бы: чтение упало бы по таймауту.
            async with client.stream(
                "GET",
                f"/api/v1/projects/{project_id}/events",
                timeout=httpx.Timeout(5, read=10),
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                server.stdin.write(b"stop\n")
                await server.stdin.drain()
                began = time.monotonic()
                body = b"".join([chunk async for chunk in response.aiter_bytes()])

        assert time.monotonic() - began < 5, _printed(output)
        # Keep-alive приходит раз в 15 с: до него поток не дожил.
        assert body == b""
        # Дальше uvicorn останавливается как обычно: процесс выходит.
        async with asyncio.timeout(10):
            await server.wait()
    finally:
        if server.returncode is None:
            server.kill()
            await server.wait()
