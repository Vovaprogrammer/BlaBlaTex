"""Общие фикстуры тестов."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Настройки тестов: без личного .env разработчика."""
    return Settings(_env_file=None, app_env="test")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Свежий экземпляр приложения на каждый тест."""
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент к приложению, без сети."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
