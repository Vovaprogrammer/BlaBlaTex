"""Общие заголовки HTTP-ответов и ожидание, которое бросают, если клиент ушёл."""

import asyncio
from collections.abc import Awaitable
from urllib.parse import quote

from fastapi import Request

# Как часто ждущий запрос проверяет, не ушёл ли клиент.
DISCONNECT_CHECK_S = 1.0

# Не ASCII или эти символы — в запасном имени _: кавычка и \ ломают строку в кавычках,
# а % старые браузеры раскодируют как %XX.
_FALLBACK_UNSAFE = frozenset('"\\%')


def content_disposition(filename: str, *, attachment: bool = False) -> str:
    """Content-Disposition: inline — открыть в браузере, attachment — скачать, и имя файла
    для «Сохранить как».

    Русское имя — в filename* (RFC 6266, кодировка по RFC 5987). В filename — для старых
    клиентов — то же имя, где символы не из ASCII, кавычки, \\ и % заменены на _.
    """
    disposition = "attachment" if attachment else "inline"
    fallback = "".join(
        char if char.isascii() and char.isprintable() and char not in _FALLBACK_UNSAFE else "_"
        for char in filename
    )
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


async def unless_client_left[T](request: Request, work: Awaitable[T]) -> T | None:
    """Результат work или None, если клиент закрыл соединение раньше: тогда work
    отменяется. uvicorn обработчик при этом не прерывает, и брошенное ожидание опрашивало
    бы базу до конца срока, а клиент с коротким таймаутом, повторяя запрос, плодил бы их."""
    task = asyncio.ensure_future(work)
    try:
        while not task.done():
            if await request.is_disconnected():
                return None
            await asyncio.wait({task}, timeout=DISCONNECT_CHECK_S)
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Отменили и нас (например, сервер останавливается) — отмена идёт дальше;
                # иначе это отмена work, которую мы и просили.
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
