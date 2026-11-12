"""Ограничитель запросов для тестов: проверки складываются в список, Redis не нужен."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.ratelimit import Counter, CountersUnavailableError, Limit, rate_limited


@dataclass(frozen=True)
class RateCheck:
    name: str
    key: str
    limit: Limit


class FakeRateLimiter:
    """RateLimiter, который запоминает проверки. retry_after задан — отвечает 429.

    Попытки входа: blocked_for() отвечает blocked_retry_after, а при unavailable — как
    без Redis; засчитанные неудачи складываются в attempts."""

    def __init__(self) -> None:
        self.checks: list[RateCheck] = []
        self.retry_after: int | None = None
        self.attempts: list[list[Counter]] = []
        self.blocked_retry_after: int | None = None
        self.unavailable = False

    async def check(self, name: str, key: str, limit: Limit) -> None:
        self.checks.append(RateCheck(name, key, limit))
        if self.retry_after is not None:
            raise rate_limited(self.retry_after)

    async def blocked_for(self, counters: Sequence[Counter]) -> int | None:
        if self.unavailable:
            raise CountersUnavailableError(10)
        return self.blocked_retry_after

    async def add_attempt(self, counters: Sequence[Counter]) -> None:
        self.attempts.append(list(counters))


class ManualClock:
    """Часы для RedisRateLimiter: время меняется только руками, окно не кончится посреди теста."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now
