"""Лимиты входа и регистрации (architecture.md 9.1, «Лимиты запросов»).

Вход считает только неудачные попытки в трёх счётчиках: почта и IP вместе, IP, почта.
Кто подбирает пароль с одного адреса, упирается в первый, а студент со своего адреса
входит как обычно; второй останавливает перебор многих почт с одного адреса, третий —
подбор одной почты с многих адресов. Те же счётчики у пароля при удалении аккаунта:
украденная сессия не станет способом подобрать пароль.
"""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Request

from app.core.ratelimit import (
    Counter,
    CountersUnavailableError,
    Limit,
    get_rate_limiter,
    rate_limited,
)
from app.modules.auth.service import WrongPasswordError, normalize_email

LOGIN_PAIR_LIMIT = Limit(count=10, period_s=15 * 60)
# Запас на общежитие, мобильный интернет и Wi-Fi вуза: там многие выходят в интернет
# с одного адреса.
LOGIN_IP_LIMIT = Limit(count=100, period_s=60 * 60)
LOGIN_EMAIL_LIMIT = Limit(count=50, period_s=60 * 60)
# Целая группа может зарегистрироваться на паре через Wi-Fi вуза — с одного адреса.
REGISTER_LIMIT = Limit(count=30, period_s=60 * 60)


@dataclass(frozen=True)
class PasswordTexts:
    """Начало текста 429: лимит исчерпан и счётчики недоступны."""

    limited: str
    unavailable: str


LOGIN_TEXTS = PasswordTexts("Слишком много попыток входа", "Вход временно недоступен")
ACCOUNT_DELETE_TEXTS = PasswordTexts(
    "Слишком много неверных паролей", "Удаление аккаунта временно недоступно"
)


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


@asynccontextmanager
async def password_attempt(
    request: Request, email: str, texts: PasswordTexts = LOGIN_TEXTS
) -> AsyncIterator[None]:
    """Проверка пароля под лимитами входа.

    Попытка засчитывается ещё до пароля, одной командой Redis: одновременные запросы не
    проскочат лимит. Лимит исчерпан — 429, пароль не проверяется. Счётчики недоступны
    (нет Redis) — тоже 429: без них пароль подбирали бы без ограничений, а кто уже вошёл,
    работает по cookie. Неверный пароль (WrongPasswordError) оставляет попытку
    засчитанной, любой другой исход — успех, 423, сбой — её возвращает.
    """
    limiter = get_rate_limiter(request)
    try:
        slot = await limiter.reserve_attempt(password_counters(request, email))
    except CountersUnavailableError as error:
        raise rate_limited(error.retry_after, texts.unavailable) from None
    if slot.retry_after is not None:
        raise rate_limited(slot.retry_after, texts.limited)
    try:
        yield
    except WrongPasswordError:
        raise
    except Exception:
        await limiter.release_attempt(slot)
        raise
    await limiter.release_attempt(slot)


async def check_registration(request: Request) -> None:
    """Засчитывает регистрацию с адреса запроса; сверх лимита — 429."""
    await get_rate_limiter(request).check("register", client_ip(request), REGISTER_LIMIT)
