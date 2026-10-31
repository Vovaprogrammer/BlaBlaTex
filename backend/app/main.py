"""Точка входа API: фабрика приложения FastAPI."""

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.health.router import router as health_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Создаёт приложение: логи, документация под /api, роутеры модулей под /api/v1."""
    configure_logging(get_settings())

    app = FastAPI(
        title="BlaBlaTex API",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(health_router, prefix=API_PREFIX)
    return app


# Объект для `fastapi dev app/main.py` и uvicorn.
app = create_app()
