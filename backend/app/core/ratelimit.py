"""Ограничение частоты запросов (architecture.md 9.1, 9.2): счётчики в Redis.

Окно фиксированной длины: счётчик запросов живёт в ключе
<префикс>:<название лимита>:<кто>:<номер окна>, команды INCR и EXPIRE идут одной транзакцией.
Запрос сверх лимита — AppError 429 rate_limited: через сколько секунд повторить — в заголовке
Retry-After и в details.retry_after.

Если Redis недоступен, запросы проходят без лимита и в лог пишется предупреждение: иначе
его падение выключило бы агентов всем студентам. После сбоя лимит PAUSE_S секунд не
проверяется — так каждый запрос не ждёт таймаута (как публикация событий в core/events.py).

check() засчитывает каждый запрос: так ограничены личные токены, сообщения, сборки и
регистрация. Вход по паролю считает только неудачные попытки: blocked_for() смотрит
счётчики, не меняя их, add_attempt() засчитывает неудачу. Входу счётчики обязательны:
без Redis blocked_for() бросает CountersUnavailableError, и вход отказывает (9.1).

Клиент Redis — один на процесс: API открывает его в lifespan (app.state.rate_limiter).
"""

import asyncio
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Protocol, Self

import structlog
from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode

logger = structlog.get_logger(__name__)

# Свой префикс ключей: Redis может быть общим с очередью задач и событиями.
KEY_PREFIX = "blablatex:ratelimit"
# Сколько проверка ждёт Redis. Дольше задерживать каждый запрос из-за лимита незачем.
CHECK_TIMEOUT_S = 1.0
# После сбоя Redis столько секунд лимит не проверяется.
PAUSE_S = 10.0
# У клиента redis по умолчанию 100 соединений на процесс. Сто первая одновременная проверка
# получила бы «Too many connections» — это RedisError, и лимиты отключились бы на PAUSE_S.
MAX_CONNECTIONS = 10_000


@dataclass(frozen=True)
class Limit:
    """Не больше count запросов за period_s секунд."""

    count: int
    period_s: int


@dataclass(frozen=True)
class Counter:
    """Счётчик попыток: название лимита, чей счётчик (IP, хеш почты) и сам лимит."""

    name: str
    key: str
    limit: Limit


class CountersUnavailableError(Exception):
    """Redis недоступен, счётчики не проверить. retry_after — через сколько секунд
    проверка снова обратится к Redis."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Счётчики лимитов недоступны, повтор через {retry_after} с")
        self.retry_after = retry_after


def wait_text(seconds: int) -> str:
    """Срок для сообщения: до минуты — в секундах, дольше — в минутах с округлением вверх."""
    if seconds < 60:
        return f"{seconds} с"
    return f"{math.ceil(seconds / 60)} мин"


def rate_limited(retry_after: int, text: str = "Слишком много запросов") -> AppError:
    """429 rate_limited: в message — text и через сколько повторить, секунды — ещё
    в details.retry_after и Retry-After."""
    return AppError(
        ErrorCode.RATE_LIMITED,
        f"{text}. Повторите через {wait_text(retry_after)}",
        429,
        {"retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


class RateLimiter(Protocol):
    async def check(self, name: str, key: str, limit: Limit) -> None:
        """Засчитывает запрос; сверх лимита — AppError 429 rate_limited.
        Redis недоступен — запрос проходит."""
        ...

    async def blocked_for(self, counters: Sequence[Counter]) -> int | None:
        """Не засчитывает. Хоть один счётчик дошёл до лимита — через сколько секунд
        повторить (самый долгий срок), иначе None. Redis недоступен — CountersUnavailableError."""
        ...

    async def add_attempt(self, counters: Sequence[Counter]) -> None:
        """Засчитывает попытку во все счётчики. Redis недоступен — ничего не делает."""
        ...


class RedisRateLimiter:
    """Счётчики запросов в Redis, окно фиксированной длины."""

    def __init__(
        self,
        redis: Redis,
        *,
        prefix: str = KEY_PREFIX,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.redis = redis
        self.prefix = prefix
        # Часы для номера окна: в тестах — свои, чтобы не ждать конца окна.
        self._clock = clock
        # До этого момента (time.monotonic) лимит не проверяется: Redis недавно был недоступен.
        self._paused_until = 0.0

    @classmethod
    def from_settings(cls, settings: Settings, *, prefix: str = KEY_PREFIX) -> Self:
        """Клиент по REDIS_URL. Подключение открывается при первом запросе, а не здесь:
        API запускается и без Redis."""
        redis = Redis.from_url(
            settings.redis_base_url,
            decode_responses=True,
            socket_timeout=CHECK_TIMEOUT_S,
            socket_connect_timeout=CHECK_TIMEOUT_S,
            max_connections=MAX_CONNECTIONS,
        )
        return cls(redis, prefix=prefix)

    async def close(self) -> None:
        """Закрывает соединения с Redis."""
        await self.redis.aclose()

    def _window_key(self, name: str, key: str, limit: Limit, now: float) -> tuple[str, int]:
        window = int(now // limit.period_s)
        return f"{self.prefix}:{name}:{key}:{window}", window

    @staticmethod
    def _retry_after(window: int, limit: Limit, now: float) -> int:
        return max(1, math.ceil((window + 1) * limit.period_s - now))

    def _unavailable(self, names: Sequence[str], error: BaseException) -> None:
        self._paused_until = time.monotonic() + PAUSE_S
        # Без key: в нём может быть IP, хеш почты или id пользователя.
        logger.warning(
            "rate_limit_unavailable", limit=",".join(names), reason=repr(error), paused_s=PAUSE_S
        )

    async def hit(self, name: str, key: str, limit: Limit) -> int | None:
        """Засчитывает запрос. Возвращает, через сколько секунд повторить, если лимит
        превышен, иначе None. Redis недоступен — None: запрос проходит без лимита."""
        if time.monotonic() < self._paused_until:
            return None
        now = self._clock()
        redis_key, window = self._window_key(name, key, limit, now)
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_S):
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.incr(redis_key)
                    # Ключ нужен только до конца своего окна; новое окно — новый ключ.
                    pipe.expire(redis_key, limit.period_s)
                    count, _ = await pipe.execute()
        except (RedisError, TimeoutError, OSError) as error:
            self._unavailable([name], error)
            return None
        if int(count) <= limit.count:
            return None
        return self._retry_after(window, limit, now)

    async def check(self, name: str, key: str, limit: Limit) -> None:
        retry_after = await self.hit(name, key, limit)
        if retry_after is not None:
            raise rate_limited(retry_after)

    async def blocked_for(self, counters: Sequence[Counter]) -> int | None:
        paused_s = self._paused_until - time.monotonic()
        if paused_s > 0:
            raise CountersUnavailableError(math.ceil(paused_s))
        now = self._clock()
        keys = [self._window_key(c.name, c.key, c.limit, now) for c in counters]
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_S):
                values = await self.redis.mget([redis_key for redis_key, _ in keys])
        except (RedisError, TimeoutError, OSError) as error:
            self._unavailable([c.name for c in counters], error)
            raise CountersUnavailableError(math.ceil(PAUSE_S)) from None
        waits = [
            self._retry_after(window, counter.limit, now)
            for counter, (_, window), value in zip(counters, keys, values, strict=True)
            if value is not None and int(value) >= counter.limit.count
        ]
        return max(waits, default=None)

    async def add_attempt(self, counters: Sequence[Counter]) -> None:
        if time.monotonic() < self._paused_until:
            return
        now = self._clock()
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_S):
                async with self.redis.pipeline(transaction=True) as pipe:
                    for counter in counters:
                        redis_key, _ = self._window_key(
                            counter.name, counter.key, counter.limit, now
                        )
                        pipe.incr(redis_key)
                        pipe.expire(redis_key, counter.limit.period_s)
                    await pipe.execute()
        except (RedisError, TimeoutError, OSError) as error:
            self._unavailable([c.name for c in counters], error)


def get_rate_limiter(request: Request) -> RateLimiter:
    """Ограничитель приложения; его открывает lifespan из create_app()."""
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        raise RuntimeError(
            "Нет ограничителя запросов: lifespan приложения не запущен. В тестах — фикстура app."
        )
    return limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
