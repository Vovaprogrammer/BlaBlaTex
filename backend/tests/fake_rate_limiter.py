"""Ограничитель запросов для тестов: проверки складываются в список, Redis не нужен."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.ratelimit import AttemptSlot, Counter, CountersUnavailableError, Limit, rate_limited


@dataclass(frozen=True)
class RateCheck:
    name: str
    key: str
    limit: Limit


class FakeRateLimiter:
    """RateLimiter, который запоминает проверки. retry_after задан — отвечает 429.

    Попытки пароля: reserve_attempt() отвечает blocked_retry_after, а при unavailable — как
    без Redis. attempts — засчитанные попытки, которые не вернули: неудачные."""

    def __init__(self) -> None:
        self.checks: list[RateCheck] = []
        self.retry_after: int | None = None
        # Засчитанные попытки; None — попытку вернули (пароль подошёл).
        self.reserved: list[list[Counter] | None] = []
        self.blocked_retry_after: int | None = None
        self.unavailable = False

    async def check(self, name: str, key: str, limit: Limit) -> None:
        self.checks.append(RateCheck(name, key, limit))
        if self.retry_after is not None:
            raise rate_limited(self.retry_after)

    @property
    def attempts(self) -> list[list[Counter]]:
        return [counters for counters in self.reserved if counters is not None]

    async def reserve_attempt(self, counters: Sequence[Counter]) -> AttemptSlot:
        if self.unavailable:
            raise CountersUnavailableError(10)
        if self.blocked_retry_after is not None:
            return AttemptSlot(retry_after=self.blocked_retry_after)
        self.reserved.append(list(counters))
        # Ключ — номер попытки: по нему release_attempt её найдёт.
        return AttemptSlot(retry_after=None, keys=(str(len(self.reserved) - 1),))

    async def release_attempt(self, slot: AttemptSlot) -> None:
        self.reserved[int(slot.keys[0])] = None


class ManualClock:
    """Часы для RedisRateLimiter: время меняется только руками, окно не кончится посреди теста."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now
