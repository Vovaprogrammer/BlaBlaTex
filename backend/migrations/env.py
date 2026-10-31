"""Окружение Alembic: async-движок, адрес из настроек приложения, метаданные всех моделей."""

import asyncio
import logging

from alembic import context
from sqlalchemy import URL, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.db import Base, import_models

config = context.config

# Сообщения о применённых миграциях — в консоль. Если логи уже настроены
# (например, pytest), basicConfig ничего не меняет.
logging.basicConfig(format="%(levelname)-5.5s [%(name)s] %(message)s")
logging.getLogger("alembic").setLevel(logging.INFO)

import_models()
target_metadata = Base.metadata


def database_url() -> URL:
    """Адрес из настроек приложения; тесты передают свой через config.attributes."""
    url: URL | None = config.attributes.get("database_url")
    return url or get_settings().database_url


def run_migrations_offline() -> None:
    """Офлайн-режим (`alembic upgrade head --sql`): печатает SQL, не подключаясь к базе."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
