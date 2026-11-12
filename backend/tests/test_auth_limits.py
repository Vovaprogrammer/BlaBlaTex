"""Лимиты входа и регистрации (architecture.md 9.1, «Лимиты запросов»).

Подбор пароля упирается в счётчики почты и IP, а студент со своего адреса входит как обычно.
Разные адреса — свои клиенты с другим client в ASGI; за Caddy адрес подставляет uvicorn.
"""

import hashlib

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import Limit, RedisRateLimiter
from app.modules.auth import limits
from app.modules.auth.models import User, UserSession
from tests.fake_rate_limiter import FakeRateLimiter, RateCheck
from tests.test_auth_api import EMAIL, PASSWORD, login, register

ATTACKER_IP = "203.0.113.7"
WRONG = "wrong-password"
EMAIL_KEY = hashlib.sha256(EMAIL.encode()).hexdigest()


def client_from(app: FastAPI, ip: str) -> AsyncClient:
    """Клиент, чьи запросы приходят с адреса ip."""
    return AsyncClient(
        transport=ASGITransport(app=app, client=(ip, 50_000)), base_url="http://test"
    )


@pytest.fixture
def redis_limits(
    app: FastAPI, rate_limiter: RedisRateLimiter, monkeypatch: pytest.MonkeyPatch
) -> RedisRateLimiter:
    """Настоящие счётчики в Redis и маленькие лимиты входа, чтобы не делать десятки попыток."""
    app.state.rate_limiter = rate_limiter
    monkeypatch.setattr(limits, "LOGIN_PAIR_LIMIT", Limit(count=3, period_s=15 * 60))
    monkeypatch.setattr(limits, "LOGIN_EMAIL_LIMIT", Limit(count=5, period_s=60 * 60))
    return rate_limiter


async def test_guessing_hits_limit_and_student_from_own_address_logs_in(
    app: FastAPI, db_client: AsyncClient, redis_limits: RedisRateLimiter
) -> None:
    await register(db_client)
    db_client.cookies.clear()

    async with client_from(app, ATTACKER_IP) as attacker:
        statuses = [(await login(attacker, password=WRONG)).status_code for _ in range(3)]
        # Лимит исчерпан: даже верный пароль не проверяется.
        refused = await login(attacker)
    student = await login(db_client)

    assert statuses == [401, 401, 401]
    assert refused.status_code == 429
    error = refused.json()["error"]
    # Часы теста стоят на начале 15-минутного окна.
    assert error == {
        "code": "rate_limited",
        "message": "Слишком много попыток входа. Повторите через 15 мин",
        "details": {"retry_after": 900},
    }
    assert refused.headers["Retry-After"] == "900"
    assert "set-cookie" not in refused.headers
    assert student.status_code == 200


async def test_unknown_email_is_limited_the_same_way(
    app: FastAPI, db_client: AsyncClient, redis_limits: RedisRateLimiter
) -> None:
    await register(db_client)
    responses = {}
    async with client_from(app, ATTACKER_IP) as attacker:
        for email in (EMAIL, "nobody@example.com"):
            for _ in range(3):
                assert (await login(attacker, email, WRONG)).status_code == 401
            responses[email] = await login(attacker, email, WRONG)

    known, unknown = responses.values()
    # По ответу не понять, есть ли такой аккаунт.
    assert known.status_code == unknown.status_code == 429
    assert known.json() == unknown.json()


async def test_email_limit_stops_guessing_from_many_addresses(
    app: FastAPI, db_client: AsyncClient, redis_limits: RedisRateLimiter
) -> None:
    await register(db_client)
    db_client.cookies.clear()
    # С каждого адреса — не больше лимита почты и IP (3), всего — лимит почты (5).
    for ip, attempts in (("203.0.113.1", 3), ("203.0.113.2", 2)):
        async with client_from(app, ip) as attacker:
            for _ in range(attempts):
                assert (await login(attacker, password=WRONG)).status_code == 401

    async with client_from(app, "203.0.113.3") as fresh:
        refused = await login(fresh)
        other_email = await login(fresh, "other@example.com", WRONG)

    assert refused.status_code == 429
    assert other_email.status_code == 401


async def test_only_failed_logins_are_counted(
    db_client: AsyncClient, rate_limits: FakeRateLimiter
) -> None:
    await register(db_client)
    db_client.cookies.clear()
    assert (await login(db_client)).status_code == 200
    assert rate_limits.attempts == []
    db_client.cookies.clear()

    assert (await login(db_client, password=WRONG)).status_code == 401

    [counters] = rate_limits.attempts
    assert [(c.name, c.key, c.limit) for c in counters] == [
        ("login_pair", f"{EMAIL_KEY}:127.0.0.1", Limit(count=10, period_s=15 * 60)),
        ("login_ip", "127.0.0.1", Limit(count=100, period_s=60 * 60)),
        ("login_email", EMAIL_KEY, Limit(count=50, period_s=60 * 60)),
    ]
    # Почты в счётчиках нет — только её хеш.
    assert EMAIL not in repr(counters)


async def test_email_case_does_not_split_counters(
    db_client: AsyncClient, rate_limits: FakeRateLimiter
) -> None:
    await login(db_client, EMAIL.upper(), WRONG)

    [counters] = rate_limits.attempts
    assert counters[2].key == EMAIL_KEY


async def test_blocked_login_checks_no_password_and_creates_no_session(
    db_client: AsyncClient, db_session: AsyncSession, rate_limits: FakeRateLimiter
) -> None:
    await register(db_client)
    db_client.cookies.clear()
    sessions_before = await db_session.scalar(select(func.count()).select_from(UserSession))
    rate_limits.blocked_retry_after = 120

    response = await login(db_client)

    assert response.status_code == 429
    assert response.json()["error"]["message"] == (
        "Слишком много попыток входа. Повторите через 2 мин"
    )
    assert rate_limits.attempts == []
    sessions_after = await db_session.scalar(select(func.count()).select_from(UserSession))
    assert sessions_after == sessions_before


async def test_login_is_refused_without_counters(
    db_client: AsyncClient, rate_limits: FakeRateLimiter
) -> None:
    await register(db_client)
    db_client.cookies.clear()
    rate_limits.unavailable = True

    response = await login(db_client)

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "rate_limited",
        "message": "Вход временно недоступен. Повторите через 10 с",
        "details": {"retry_after": 10},
    }
    assert response.headers["Retry-After"] == "10"


async def test_registration_is_limited_per_address(
    db_client: AsyncClient, db_session: AsyncSession, rate_limits: FakeRateLimiter
) -> None:
    rate_limits.retry_after = 1800

    response = await register(db_client, password=PASSWORD)

    assert response.status_code == 429
    assert response.json()["error"]["message"] == "Слишком много запросов. Повторите через 30 мин"
    assert rate_limits.checks == [
        RateCheck("register", "127.0.0.1", Limit(count=30, period_s=60 * 60))
    ]
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0
