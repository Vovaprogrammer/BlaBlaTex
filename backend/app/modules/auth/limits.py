"""Лимиты входа и регистрации (architecture.md 9.1, «Лимиты запросов»).

Вход считает только неудачные попытки в трёх счётчиках: почта и IP вместе, IP, почта.
Кто подбирает пароль с одного адреса, упирается в первый, а студент со своего адреса
входит как обычно; второй останавливает перебор многих почт с одного адреса, третий —
подбор одной почты с многих адресов.
"""

import hashlib

from fastapi import Request

from app.core.ratelimit import (
    Counter,
    CountersUnavailableError,
    Limit,
    get_rate_limiter,
    rate_limited,
)
from app.modules.auth.service import normalize_email

LOGIN_PAIR_LIMIT = Limit(count=10, period_s=15 * 60)
# Запас на компьютерный класс или общежитие, где все выходят в интернет с одного адреса.
LOGIN_IP_LIMIT = Limit(count=100, period_s=60 * 60)
LOGIN_EMAIL_LIMIT = Limit(count=50, period_s=60 * 60)
# Целая группа в компьютерном классе регистрируется с одного адреса.
REGISTER_LIMIT = Limit(count=30, period_s=60 * 60)

LOGIN_LIMITED_TEXT = "Слишком много попыток входа"
LOGIN_UNAVAILABLE_TEXT = "Вход временно недоступен"


def client_ip(request: Request) -> str:
    """IP клиента. За Caddy его уже подставил uvicorn из X-Forwarded-For — только для
    запросов с адресов из FORWARDED_ALLOW_IPS (architecture.md 13)."""
    return request.client.host if request.client is not None else "unknown"


def _email_key(email: str) -> str:
    # В Redis — хеш, а не почта: в счётчиках не должно быть персональных данных.
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()


def password_counters(request: Request, email: str) -> list[Counter]:
    """Счётчики неудачных попыток пароля к этой почте с адреса запроса.

    Одинаковы для зарегистрированной почты и неизвестной: по ответу не понять, есть ли
    такой аккаунт."""
    ip = client_ip(request)
    email_key = _email_key(email)
    return [
        Counter("login_pair", f"{email_key}:{ip}", LOGIN_PAIR_LIMIT),
        Counter("login_ip", ip, LOGIN_IP_LIMIT),
        Counter("login_email", email_key, LOGIN_EMAIL_LIMIT),
    ]


async def check_password_attempts(request: Request, counters: list[Counter]) -> None:
    """До проверки пароля: лимит неудачных попыток исчерпан — 429, пароль не проверяется.

    Счётчики недоступны (нет Redis) — тоже 429: без них пароль подбирали бы без
    ограничений, а кто уже вошёл, работает по cookie."""
    try:
        retry_after = await get_rate_limiter(request).blocked_for(counters)
    except CountersUnavailableError as error:
        raise rate_limited(error.retry_after, LOGIN_UNAVAILABLE_TEXT) from None
    if retry_after is not None:
        raise rate_limited(retry_after, LOGIN_LIMITED_TEXT)


async def count_failed_attempt(request: Request, counters: list[Counter]) -> None:
    """Засчитывает неудачную попытку во все счётчики."""
    await get_rate_limiter(request).add_attempt(counters)


async def check_registration(request: Request) -> None:
    """Засчитывает регистрацию с адреса запроса; сверх лимита — 429."""
    await get_rate_limiter(request).check("register", client_ip(request), REGISTER_LIMIT)
