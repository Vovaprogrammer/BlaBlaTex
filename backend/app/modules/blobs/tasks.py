"""Ночная уборка хранилища в воркере (architecture.md 5, «Уборка хранилища»)."""

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.storage import Storage
from app.modules.blobs import service

logger = structlog.get_logger(__name__)

# Первая уборка — вскоре после запуска: воркер перезапускают при каждом обновлении,
# и при одних только суточных паузах уборка могла бы не дойти до дела никогда.
FIRST_SWEEP_DELAY_S = 10 * 60
SWEEP_INTERVAL_S = 24 * 60 * 60


async def watch_storage(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    *,
    first_delay_s: float = FIRST_SWEEP_DELAY_S,
    interval_s: float = SWEEP_INTERVAL_S,
) -> None:
    """Убирает ничьи blob'ы через first_delay_s после запуска и потом каждые interval_s,
    пока работает воркер. Сбой одной уборки не останавливает следующие.

    Если воркеров несколько, уборку делает каждый: замок на blob не даст им помешать
    друг другу, лишней будет только проверка ссылок."""
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            async with sessionmaker() as session:
                result = await service.sweep(session, storage)
            logger.info(
                "storage_swept", deleted=result.deleted, kept=result.kept, failed=result.failed
            )
        except Exception:
            logger.exception("storage_sweep_failed")
        await asyncio.sleep(interval_s)
