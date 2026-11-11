"""Ограничение частоты запросов (architecture.md 9.1, 9.2): счётчики в Redis.

Окно фиксированной длины: счётчик запросов живёт в ключе
<префикс>:<название лимита>:<кто>:<номер окна>, команды INCR и EXPIRE идут одной транзакцией.
Запрос сверх лимита — AppError 429 rate_limited: через сколько секунд повторить — в заголовке
Retry-After и в details.retry_after.

Если Redis недоступен, запросы проходят без лимита и в лог пишется предупреждение: иначе
его падение выключило бы агентов всем студентам. После сбоя лимит PAUSE_S секунд не
проверяется — так каждый запрос не ждёт таймаута (как публикация событий в core/events.py).

Сейчас лимит стоит на личных токенах (B4.1). Вход, сообщения и сборки (B3.3) получают
свой Limit и ключ — IP или пользователя — и вызывают тот же check().

Клиент Redis — один на процесс: API открывает его в lifespan (app.state.rate_limiter).
"""

import asyncio
import math
import time
from collections.abc import Callable
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


@dataclass(frozen=True)
class Limit:
    """Не больше count запросов за period_s секунд."""

    count: int
    period_s: int


def rate_limited(retry_after: int) -> AppError:
    return AppError(
        ErrorCode.RATE_LIMITED,
        f"Слишком много запросов. Повторите через {retry_after} с",
        429,
        {"retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


class RateLimiter(Protocol):
    async def check(self, name: str, key: str, limit: Limit) -> None:
        """Засчитывает запрос; сверх лимита — AppError 429 rate_limited."""
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
        )
        return cls(redis, prefix=prefix)

    async def close(self) -> None:
        """Закрывает соединения с Redis."""
        await self.redis.aclose()

    async def hit(self, name: str, key: str, limit: Limit) -> int | None:
        """Засчитывает запрос. Возвращает, через сколько секунд повторить, если лимит
        превышен, иначе None. Redis недоступен — None: запрос проходит без лимита."""
        if time.monotonic() < self._paused_until:
            return None
        now = self._clock()
        window = int(now // limit.period_s)
        redis_key = f"{self.prefix}:{name}:{key}:{window}"
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_S):
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.incr(redis_key)
                    # Ключ нужен только до конца своего окна; новое окно — новый ключ.
                    pipe.expire(redis_key, limit.period_s)
                    count, _ = await pipe.execute()
        except (RedisError, TimeoutError, OSError) as error:
            self._paused_until = time.monotonic() + PAUSE_S
            # Без key: в нём может быть IP или id пользователя.
            logger.warning(
                "rate_limit_unavailable", limit=name, reason=repr(error), paused_s=PAUSE_S
            )
            return None
        if int(count) <= limit.count:
            return None
        return max(1, math.ceil((window + 1) * limit.period_s - now))

    async def check(self, name: str, key: str, limit: Limit) -> None:
        retry_after = await self.hit(name, key, limit)
        if retry_after is not None:
            raise rate_limited(retry_after)


def get_rate_limiter(request: Request) -> RateLimiter:
    """Ограничитель приложения; его открывает lifespan из create_app()."""
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        raise RuntimeError(
            "Нет ограничителя запросов: lifespan приложения не запущен. В тестах — фикстура app."
        )
    return limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
