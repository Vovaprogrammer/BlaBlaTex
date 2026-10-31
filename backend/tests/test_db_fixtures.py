"""Фикстуры с реальным Postgres: тестовая база, откат после теста, сессия в роутах."""

import uuid
from datetime import UTC, datetime

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped

from app.core.config import Settings
from app.core.db import (
    Base,
    CreatedAtMixin,
    DbSession,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
    import_models,
)
from app.main import create_app


class NotesBase(DeclarativeBase):
    """Своя база для тестовых моделей, чтобы они не попали в Base.metadata и миграции."""


class Note(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, NotesBase):
    __tablename__ = "test_notes"

    title: Mapped[str]


async def create_notes_table(session: AsyncSession) -> None:
    # DDL в Postgres транзакционный: таблица исчезнет вместе с откатом теста.
    await session.run_sync(lambda s: NotesBase.metadata.create_all(s.connection()))


async def test_commit_inside_test_stays_in_outer_transaction(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    await create_notes_table(db_session)
    db_session.add(Note(title="черновик"))
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(Note)) == 1
    # Другое соединение не видит ни таблицы, ни строки: внешняя транзакция не закоммичена.
    async with db_engine.connect() as other:
        assert await other.scalar(text("select to_regclass('test_notes')")) is None


async def test_mixins_fill_id_and_timestamps(db_session: AsyncSession) -> None:
    await create_notes_table(db_session)
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    note = Note(title="отчёт", updated_at=long_ago)
    db_session.add(note)
    await db_session.flush()

    assert isinstance(note.id, uuid.UUID)
    assert note.created_at.tzinfo is not None

    note.title = "отчёт по ЛР 1"
    await db_session.flush()
    await db_session.refresh(note)

    assert note.updated_at > long_ago
    assert note.updated_at.tzinfo is not None


async def test_database_defaults_fill_raw_sql_inserts(db_session: AsyncSession) -> None:
    await create_notes_table(db_session)

    row = (
        await db_session.execute(
            text("insert into test_notes (title) values ('из миграции') returning *")
        )
    ).one()

    assert isinstance(row.id, uuid.UUID)
    assert row.created_at is not None
    assert row.updated_at is not None


async def test_migrations_match_models(db_engine: AsyncEngine) -> None:
    import_models()

    def compare(connection: Connection) -> list[object]:
        return compare_metadata(MigrationContext.configure(connection), Base.metadata)

    async with db_engine.connect() as connection:
        diff = await connection.run_sync(compare)

    assert diff == [], "Модели расходятся с миграциями: uv run alembic revision --autogenerate"


async def test_app_session_works_with_test_database(db_settings: Settings) -> None:
    app = create_app(db_settings)

    @app.get("/test-db")
    async def route(session: DbSession) -> str | None:
        return await session.scalar(text("select current_database()"))

    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/test-db")

    assert response.json() == db_settings.postgres_db


async def test_db_client_routes_use_test_session(
    app: FastAPI, db_client: AsyncClient, db_session: AsyncSession
) -> None:
    seen: list[AsyncSession] = []

    @app.get("/test-session")
    async def route(session: DbSession) -> None:
        seen.append(session)

    response = await db_client.get("/test-session")

    assert response.status_code == 200
    assert seen == [db_session]
