"""Защита от CSRF: небезопасный запрос с cookie сессии требует X-CSRF-Protection: 1."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

COOKIE = {"Cookie": "bbt_session=any-token"}
UNSAFE = ["POST", "PUT", "PATCH", "DELETE"]


@pytest.fixture
def guarded(app: FastAPI, client: AsyncClient) -> AsyncClient:
    """Клиент к приложению с тестовым маршрутом: защита стоит на всех маршрутах приложения."""

    @app.api_route("/test-csrf", methods=["GET", *UNSAFE])
    async def route() -> str:
        return "ok"

    return client


@pytest.mark.parametrize("method", UNSAFE)
@pytest.mark.parametrize("header", [None, "0", "true"])
async def test_unsafe_request_with_cookie_needs_csrf_header(
    guarded: AsyncClient, method: str, header: str | None
) -> None:
    headers = COOKIE | ({"X-CSRF-Protection": header} if header is not None else {})

    response = await guarded.request(method, "/test-csrf", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("method", UNSAFE)
async def test_unsafe_request_with_csrf_header_passes(guarded: AsyncClient, method: str) -> None:
    headers = COOKIE | {"X-CSRF-Protection": "1"}

    response = await guarded.request(method, "/test-csrf", headers=headers)

    assert response.status_code == 200


async def test_safe_request_with_cookie_does_not_need_header(guarded: AsyncClient) -> None:
    response = await guarded.get("/test-csrf", headers=COOKIE)

    assert response.status_code == 200


async def test_request_without_cookie_is_not_checked(guarded: AsyncClient) -> None:
    # Так будут ходить MCP и скрипты: с Authorization: Bearer, без cookie.
    response = await guarded.post("/test-csrf")

    assert response.status_code == 200


async def test_api_routes_check_csrf_before_anything_else(client: AsyncClient) -> None:
    # Проверка идёт раньше сессии и тела запроса: базе и валидации дело не доходит.
    response = await client.put("/api/v1/profile", headers=COOKIE)

    assert response.status_code == 403
