"""Движок и сессия БД без подключения к Postgres: соединение открывается только при запросе."""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import DbSession


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
