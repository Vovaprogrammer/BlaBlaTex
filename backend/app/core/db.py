"""Подключение к Postgres: движок, фабрика сессий и зависимость get_session."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Движок с пулом соединений. Соединения открываются при первом запросе, а не здесь."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Проверять соединение перед выдачей: после перезапуска Postgres старые мертвы.
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # После commit объекты не сбрасываются: в async ленивая подгрузка атрибутов падает.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Сессия БД на один запрос; фабрику кладёт в app.state lifespan из create_app().

    Коммит делает сервис явно: `await session.commit()`. Всё незакоммиченное
    откатывается, когда сессия закрывается после ответа.
    """
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
