"""Лимиты запросов (core/ratelimit.py): счётчики на настоящем Redis, окно фиксированной длины."""

from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from structlog.testing import capture_logs

from app.core.errors import AppError
from app.core.ratelimit import Limit, RedisRateLimiter
from tests.fake_rate_limiter import ManualClock

LIMIT = Limit(count=3, period_s=60)


async def test_counts_requests_in_window(rate_limiter: RedisRateLimiter) -> None:
    allowed = [await rate_limiter.hit("api_token", "t1", LIMIT) for _ in range(3)]
    refused = await rate_limiter.hit("api_token", "t1", LIMIT)

    assert allowed == [None, None, None]
    assert refused is not None


async def test_names_and_keys_are_counted_separately(rate_limiter: RedisRateLimiter) -> None:
    for _ in range(3):
        await rate_limiter.hit("api_token", "t1", LIMIT)

    assert await rate_limiter.hit("api_token", "t2", LIMIT) is None
    assert await rate_limiter.hit("login", "t1", LIMIT) is None
    assert await rate_limiter.hit("api_token", "t1", LIMIT) is not None


async def test_new_window_starts_from_zero(
    rate_limiter: RedisRateLimiter, clock: ManualClock
) -> None:
    for _ in range(4):
        await rate_limiter.hit("api_token", "t1", LIMIT)

    clock.now += LIMIT.period_s

    assert await rate_limiter.hit("api_token", "t1", LIMIT) is None


async def test_retry_after_is_time_left_in_window(
    rate_limiter: RedisRateLimiter, clock: ManualClock
) -> None:
    # Окно начинается на границе минуты; 15.2 с уже прошло — ждать 45 с (вверх до целых).
    clock.now = 1_800_000_000 // 60 * 60 + 15.2
    for _ in range(3):
        await rate_limiter.hit("api_token", "t1", LIMIT)

    with pytest.raises(AppError) as raised:
        await rate_limiter.check("api_token", "t1", LIMIT)

    error = raised.value
    assert (error.status, error.code) == (429, "rate_limited")
    assert error.details == {"retry_after": 45}
    assert error.headers == {"Retry-After": "45"}
    assert error.message == "Слишком много запросов. Повторите через 45 с"


async def test_counter_key_expires_with_window(rate_limiter: RedisRateLimiter) -> None:
    await rate_limiter.hit("api_token", "t1", LIMIT)

    keys = [key async for key in rate_limiter.redis.scan_iter(match=f"{rate_limiter.prefix}:*")]
    assert len(keys) == 1
    assert 0 < await rate_limiter.redis.ttl(keys[0]) <= LIMIT.period_s


class BrokenRedis:
    """Redis, который не отвечает: считает, сколько раз к нему обратились."""

    def __init__(self) -> None:
        self.calls = 0

    def pipeline(self, **_: Any) -> None:  # Any: аргументы клиента redis не важны
        self.calls += 1
        raise RedisConnectionError("Redis недоступен")


async def test_without_redis_requests_pass_and_redis_is_not_asked_again() -> None:
    redis = BrokenRedis()
    limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]

    with capture_logs() as logs:
        first = await limiter.hit("api_token", "secret-key", LIMIT)
        await limiter.check("api_token", "secret-key", LIMIT)

    assert first is None
    # После сбоя лимит не проверяется: второй запрос не ждёт Redis.
    assert redis.calls == 1
    assert [log["event"] for log in logs] == ["rate_limit_unavailable"]
    # Ключ (IP, id пользователя или токена) в лог не попадает.
    assert "secret-key" not in str(logs)
