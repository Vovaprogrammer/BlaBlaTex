"""Общие фикстуры тестов."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP-клиент к свежему экземпляру приложения, без сети."""
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as ac:
        yield ac
