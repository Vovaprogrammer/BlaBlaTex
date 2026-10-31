"""Слой БД без подключения к Postgres: соединение открывается только при запросе."""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.config import Settings
from app.core.db import (
    Base,
    CreatedAtMixin,
    DbSession,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
    import_models,
)


def ddl(element: CreateTable | CreateIndex) -> str:
    return str(element.compile(dialect=postgresql.dialect()))


async def test_lifespan_creates_engine_from_settings(app: FastAPI, settings: Settings) -> None:
    async with app.router.lifespan_context(app):
        engine = app.state.db_engine

        assert engine.url == settings.database_url
        assert engine.pool.size() == settings.db_pool_size


async def test_get_session_gives_new_session_on_app_engine(
    app: FastAPI, client: AsyncClient
) -> None:
    seen: list[AsyncSession] = []

    @app.get("/test-session")
    async def route(session: DbSession) -> None:
        seen.append(session)

    async with app.router.lifespan_context(app):
        for _ in range(2):
            response = await client.get("/test-session")
            assert response.status_code == 200

        assert seen[0].bind is app.state.db_engine
        assert seen[0] is not seen[1]


def test_constraint_names_follow_convention() -> None:
    # Отдельный MetaData с тем же соглашением, чтобы не добавлять таблицы в Base.metadata.
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    Table("projects", metadata, Column("id", Integer, primary_key=True))
    files = Table(
        "files",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("project_id", ForeignKey("projects.id"), index=True),
        Column("path", String),
        UniqueConstraint("project_id", "path"),
        CheckConstraint("path <> ''", name="path_not_empty"),
    )

    table_ddl = ddl(CreateTable(files))

    assert "CONSTRAINT pk_files PRIMARY KEY" in table_ddl
    assert "CONSTRAINT fk_files_project_id_projects FOREIGN KEY" in table_ddl
    assert "CONSTRAINT uq_files_project_id_path UNIQUE" in table_ddl
    assert "CONSTRAINT ck_files_path_not_empty CHECK" in table_ddl
    assert "CREATE INDEX ix_files_project_id" in ddl(CreateIndex(next(iter(files.indexes))))


def test_mixins_give_uuid_pk_and_timezone_aware_timestamps() -> None:
    class TestBase(DeclarativeBase):
        pass

    class Note(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, TestBase):
        __tablename__ = "notes"

        title: Mapped[str]

    table_ddl = ddl(CreateTable(Note.__table__))

    assert "id UUID DEFAULT gen_random_uuid() NOT NULL" in table_ddl
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in table_ddl
    assert "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in table_ddl
    assert Note.__table__.c.updated_at.onupdate is not None
    assert Note.__table__.c.created_at.onupdate is None


def test_import_models_imports_only_existing_models_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "fake_modules"
    for module in ("with_models", "without_models"):
        (package / module).mkdir(parents=True)
        (package / module / "__init__.py").touch()
    (package / "__init__.py").touch()
    (package / "with_models" / "models.py").touch()
    monkeypatch.syspath_prepend(tmp_path)
    try:
        import_models("fake_modules")

        assert "fake_modules.with_models.models" in sys.modules
        assert "fake_modules.without_models.models" not in sys.modules
    finally:
        for name in [n for n in sys.modules if n.startswith("fake_modules")]:
            del sys.modules[name]
