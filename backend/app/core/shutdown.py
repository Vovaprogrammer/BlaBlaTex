"""Отметка «сервер останавливается» для ответов без конца — потоков событий (9.3).

uvicorn при остановке перестаёт принимать соединения и ждёт, пока закончатся открытые
ответы, — без срока: fastapi dev и fastapi run его не задают. lifespan shutdown наступает
только после этого. Поток событий сам не кончается, и без отметки процесс ждал бы вкладку
вечно: fastapi dev не перезапускался после правки кода и API не отвечал, а при деплое
процесс ждал бы, пока его убьют.

Поэтому на время работы приложения перед обработчиком сигналов uvicorn встаёт свой: он
ставит отметку и передаёт сигнал дальше. Потоки по отметке заканчиваются, вкладки
переподключаются к новому процессу с Last-Event-ID и получают пропущенное из журнала.
"""

import asyncio
import signal
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager, suppress
from types import FrameType
from typing import Annotated, Any

from fastapi import Depends, Request

# Сигналы, по которым останавливается uvicorn: Ctrl+C (им же fastapi dev на Windows
# перезапускает процесс после правки), kill и docker stop, на Windows ещё Ctrl+Break.
SHUTDOWN_SIGNALS: tuple[signal.Signals, ...] = tuple(
    getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGBREAK") if hasattr(signal, name)
)

# Any: так типизирован обработчик сигнала в signal — что он вернёт, не используется.
SignalHandler = Callable[[int, FrameType | None], Any]


class Shutdown:
    """Отметка остановки сервера: её ждут ответы, которые иначе не кончатся."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def is_set(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        self._event.set()

    async def unless_stopped[T](self, work: Awaitable[T]) -> T | None:
        """Результат work или None, если сервер начал останавливаться раньше: тогда work
        отменяется."""
        task = asyncio.ensure_future(work)
        stopped = asyncio.ensure_future(self._event.wait())
        try:
            await asyncio.wait({task, stopped}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopped.cancel()
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    # Отменили и нас (например, вкладка закрылась) — отмена идёт дальше;
                    # иначе это отмена work, которую мы и просили.
                    current = asyncio.current_task()
                    if current is not None and current.cancelling():
                        raise
        return task.result() if not task.cancelled() else None

    @contextmanager
    def on_signals(self) -> Iterator[None]:
        """Пока открыт, сигнал остановки сначала ставит отметку, потом идёт прежнему
        обработчику — uvicorn. Сигнал, который никто не перехватывает, не трогается:
        процесс по нему и так остановится сразу.

        Обработчики сигналов Python ставит только в главном потоке; в другом (например,
        TestClient) ничего не меняется.

        Отметка каждый раз новая: прошлая остановка того же приложения (второй lifespan
        в одном процессе) не должна сразу закрывать новые потоки, а событие asyncio
        привязано к циклу, в котором его ждали.
        """
        self._event = asyncio.Event()
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        loop = asyncio.get_running_loop()
        installed: dict[signal.Signals, tuple[SignalHandler, SignalHandler]] = {}
        for signum in SHUTDOWN_SIGNALS:
            previous = signal.getsignal(signum)
            if not callable(previous):
                continue
            handler = self._handler(loop, previous)
            signal.signal(signum, handler)
            installed[signum] = (previous, handler)
        try:
            yield
        finally:
            for signum, (previous, handler) in installed.items():
                # Кто-то поставил свой поверх — его не трогаем.
                if signal.getsignal(signum) is handler:
                    signal.signal(signum, previous)

    def _handler(self, loop: asyncio.AbstractEventLoop, previous: SignalHandler) -> SignalHandler:
        def handle(signum: int, frame: FrameType | None) -> None:
            # Обработчик сигнала прерывает код где угодно: отметка ставится через цикл
            # событий. Цикл уже закрыт — ставить её некому и незачем.
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(self.set)
            previous(signum, frame)

        return handle


def get_shutdown(request: Request) -> Shutdown:
    return request.app.state.shutdown


ShutdownDep = Annotated[Shutdown, Depends(get_shutdown)]
