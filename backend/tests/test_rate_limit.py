"""Лимиты запросов (core/ratelimit.py): счётчики на настоящем Redis, окно фиксированной длины."""

from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from structlog.testing import capture_logs

from app.core.config import Settings
from app.core.errors import AppError
from app.core.ratelimit import (
    MAX_CONNECTIONS,
    Counter,
    CountersUnavailableError,
    Limit,
    RedisRateLimiter,
    rate_limited,
)
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


async def test_pool_allows_many_concurrent_checks() -> None:
    # С пулом по умолчанию (100) сто первая одновременная проверка отключила бы лимиты.
    limiter = RedisRateLimiter.from_settings(Settings(app_env="test"))
    try:
        assert limiter.redis.connection_pool.max_connections == MAX_CONNECTIONS
        assert MAX_CONNECTIONS >= 1000
    finally:
        await limiter.close()


async def test_attempts_are_counted_only_when_added(rate_limiter: RedisRateLimiter) -> None:
    counters = [Counter("login_pair", "k1", LIMIT), Counter("login_ip", "ip", Limit(10, 60))]

    for _ in range(5):
        assert await rate_limiter.blocked_for(counters) is None
    for _ in range(3):
        await rate_limiter.add_attempt(counters)

    # Третья неудача исчерпала лимит login_pair: дальше — отказ до конца окна.
    assert await rate_limiter.blocked_for(counters) is not None
    assert await rate_limiter.blocked_for([counters[1]]) is None


async def test_blocked_for_answers_with_longest_wait(
    rate_limiter: RedisRateLimiter, clock: ManualClock
) -> None:
    short = Counter("login_pair", "k", Limit(count=1, period_s=60))
    long = Counter("login_email", "k", Limit(count=1, period_s=3600))
    await rate_limiter.add_attempt([short, long])
    clock.now += 30

    # Часы теста стоят на начале окна.
    assert await rate_limiter.blocked_for([short, long]) == 3570
    assert await rate_limiter.blocked_for([short]) == 30


async def test_attempt_counters_expire_with_window(rate_limiter: RedisRateLimiter) -> None:
    await rate_limiter.add_attempt([Counter("login_ip", "ip", LIMIT)])

    keys = [key async for key in rate_limiter.redis.scan_iter(match=f"{rate_limiter.prefix}:*")]
    assert len(keys) == 1
    assert 0 < await rate_limiter.redis.ttl(keys[0]) <= LIMIT.period_s


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(1, "1 с"), (59, "59 с"), (60, "1 мин"), (61, "2 мин"), (900, "15 мин"), (3600, "60 мин")],
)
def test_message_says_when_to_retry(seconds: int, text: str) -> None:
    error = rate_limited(seconds, "Слишком много попыток входа")

    assert error.message == f"Слишком много попыток входа. Повторите через {text}"
    assert error.details == {"retry_after": seconds}
    assert error.headers == {"Retry-After": str(seconds)}


class BrokenRedis:
    """Redis, который не отвечает: считает, сколько раз к нему обратились."""

    def __init__(self) -> None:
        self.calls = 0

    def pipeline(self, **_: Any) -> None:  # Any: аргументы клиента redis не важны
        self.calls += 1
        raise RedisConnectionError("Redis недоступен")

    async def mget(self, *_: Any) -> None:  # Any: аргументы клиента redis не важны
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


async def test_without_redis_attempts_are_refused_and_failures_are_dropped() -> None:
    redis = BrokenRedis()
    limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]
    counters = [Counter("login_email", "email-hash", LIMIT)]

    with capture_logs() as logs:
        with pytest.raises(CountersUnavailableError) as first:
            await limiter.blocked_for(counters)
        # Пока Redis на паузе, к нему не обращаемся, но отказываем.
        with pytest.raises(CountersUnavailableError) as second:
            await limiter.blocked_for(counters)
        await limiter.add_attempt(counters)

    assert first.value.retry_after == 10
    assert 1 <= second.value.retry_after <= 10
    assert redis.calls == 1
    assert [log["event"] for log in logs] == ["rate_limit_unavailable"]
    assert "email-hash" not in str(logs)
