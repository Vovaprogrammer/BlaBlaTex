"""Остановка сервера закрывает потоки событий (core/shutdown.py, architecture.md 9.3).

uvicorn при остановке ждёт открытые ответы без срока, поэтому без отметки остановки
открытая вкладка проекта не давала fastapi dev перезапуститься после правки кода.
"""

import asyncio
import signal
import socket
import subprocess
import sys
import time
import uuid
from types import FrameType

import httpx

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


def _wait_until_up(base: str, server: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        assert server.poll() is None, "сервер не запустился"
        try:
            if httpx.get(f"{base}/api/v1/health", timeout=1).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    raise AssertionError("сервер не ответил за 30 с")


def test_open_event_stream_closes_when_server_stops() -> None:
    port, project_id = _free_port(), uuid.uuid4()
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-c", _SERVER, str(port), str(project_id)],
        cwd=BACKEND_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert server.stdin is not None
    try:
        _wait_until_up(base, server)
        # Без отметки остановки поток не кончился бы: чтение упало бы по таймауту.
        timeout = httpx.Timeout(5, read=10)
        with httpx.stream(
            "GET", f"{base}/api/v1/projects/{project_id}/events", timeout=timeout
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            server.stdin.write(b"stop\n")
            server.stdin.flush()
            began = time.monotonic()
            body = b"".join(response.iter_bytes())

        assert time.monotonic() - began < 5
        # Keep-alive приходит раз в 15 с: до него поток не дожил.
        assert body == b""
        # Дальше uvicorn останавливается как обычно: процесс выходит.
        server.wait(timeout=10)
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
