"""Подключение к Postgres: движок, фабрика сессий, get_session и базовый класс моделей."""

import importlib
import importlib.util
import pkgutil
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, ClassVar

from fastapi import Depends, Request
from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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


# Имена ограничений и индексов по шаблону: Alembic находит и удаляет их по имени,
# поэтому имя не должно зависеть от базы. Длинные имена SQLAlchemy сам укорачивает до 63.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс всех моделей. Любое поле datetime в базе — timestamptz."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[type, DateTime]] = {datetime: DateTime(timezone=True)}


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Значения ставит приложение: так они известны сразу после flush, без лишнего запроса,
# который в async упал бы. DEFAULT в самой базе — для вставок SQL из миграций.


class UUIDPrimaryKeyMixin:
    """Первичный ключ id — случайный uuid."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )


class CreatedAtMixin:
    """Время создания строки."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class UpdatedAtMixin:
    """Время последнего изменения; обновляется при каждом UPDATE через SQLAlchemy."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


def import_models(package: str = "app.modules") -> None:
    """Импортирует <package>/*/models.py, чтобы все таблицы попали в Base.metadata.

    Нужно Alembic: автогенерация видит только импортированные модели.
    """
    root = importlib.import_module(package)
    for module in pkgutil.iter_modules(root.__path__):
        name = f"{package}.{module.name}.models"
        if module.ispkg and importlib.util.find_spec(name) is not None:
            importlib.import_module(name)
