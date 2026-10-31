"""Точка входа API: фабрика приложения FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.errors import ERROR_RESPONSES, register_error_handlers
from app.core.logging import configure_logging
from app.modules.auth.router import router as auth_router
from app.modules.builds.router import router as builds_router
from app.modules.health.router import router as health_router
from app.modules.profiles.router import router as profiles_router
from app.modules.projects.router import router as projects_router
from app.modules.templates.router import router as templates_router

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение: логи, БД, ошибки по 9.2, документация под /api, роутеры под /api/v1.

    Без аргумента настройки берутся из окружения и .env; тесты передают свои.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Пул соединений живёт, пока работает сервер, и закрывается при остановке.
        engine = create_engine(settings)
        app.state.db_engine = engine
        app.state.db_sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="BlaBlaTex API",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(health_router, prefix=API_PREFIX)
    for router in (auth_router, profiles_router, templates_router, projects_router, builds_router):
        app.include_router(router, prefix=API_PREFIX, responses=ERROR_RESPONSES)
    return app


# Объект для `fastapi dev app/main.py` и uvicorn.
app = create_app()
