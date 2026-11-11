"""Ограничитель запросов для тестов: проверки складываются в список, Redis не нужен."""

from dataclasses import dataclass

from app.core.ratelimit import Limit, rate_limited


@dataclass(frozen=True)
class RateCheck:
    name: str
    key: str
    limit: Limit


class FakeRateLimiter:
    """RateLimiter, который запоминает проверки. retry_after задан — отвечает 429."""

    def __init__(self) -> None:
        self.checks: list[RateCheck] = []
        self.retry_after: int | None = None

    async def check(self, name: str, key: str, limit: Limit) -> None:
        self.checks.append(RateCheck(name, key, limit))
        if self.retry_after is not None:
            raise rate_limited(self.retry_after)


class ManualClock:
    """Часы для RedisRateLimiter: время меняется только руками, окно не кончится посреди теста."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now
