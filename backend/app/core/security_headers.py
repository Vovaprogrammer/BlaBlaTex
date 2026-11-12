"""Заголовки безопасности у ответов API (architecture.md 13).

API ставит их у всех своих ответов, а Caddy в проде — HSTS на весь сайт и заголовки
статики фронта: к ответам /api он своих не добавляет, поэтому дублей и противоречий нет.

Заголовок ставится, только если обработчик не поставил такой сам: у файлов свои nosniff,
Content-Disposition и CSP sandbox (у SVG) — они остаются как есть. CSP и запрет кеша —
только у JSON: CSP мешал бы просмотрщику PDF в браузере, а файлам и PDF кеш не вредит.

Middleware чистый ASGI, а не BaseHTTPMiddleware: потоки (SSE, PDF) идут без буфера.
Ответ 500 на непойманное исключение отдаёт ServerErrorMiddleware снаружи всех middleware —
в нём этих заголовков нет, но и данных студента тоже.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# У всех ответов API.
COMMON_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # Чужой сайт не встроит ответ API, а наш фронт может (например, PDF в iframe).
    "X-Frame-Options": "SAMEORIGIN",
    # Ссылка из PDF, открытого в браузере, не отдаст чужому сайту адрес файла.
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# Только у JSON: браузер не сохраняет данные студента на диск — интерфейсу они нужны
# только в памяти (TanStack Query).
JSON_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware:
    """Добавляет заголовки безопасности, которых у ответа ещё нет."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                for name, value in COMMON_HEADERS.items():
                    headers.setdefault(name, value)
                if headers.get("content-type", "").startswith("application/json"):
                    for name, value in JSON_HEADERS.items():
                        headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
