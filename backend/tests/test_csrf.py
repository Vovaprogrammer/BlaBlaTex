"""Защита от CSRF: небезопасный запрос с cookie сессии требует X-CSRF-Protection: 1."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

PID = uuid4()
COOKIE = {"Cookie": "bbt_session=any-token"}

# По одному маршруту API на каждый небезопасный метод.
UNSAFE = [
    ("POST", "/api/v1/auth/logout"),
    ("PUT", "/api/v1/profile"),
    ("PATCH", f"/api/v1/projects/{PID}"),
    ("DELETE", f"/api/v1/projects/{PID}"),
]
IDS = [method for method, _ in UNSAFE]


@pytest.mark.parametrize(("method", "path"), UNSAFE, ids=IDS)
@pytest.mark.parametrize("header", [None, "0", "true"])
async def test_unsafe_request_with_cookie_needs_csrf_header(
    db_client: AsyncClient, method: str, path: str, header: str | None
) -> None:
    headers = COOKIE | ({"X-CSRF-Protection": header} if header is not None else {})

    response = await db_client.request(method, path, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize(("method", "path"), UNSAFE, ids=IDS)
async def test_unsafe_request_with_csrf_header_passes(
    db_client: AsyncClient, method: str, path: str
) -> None:
    response = await db_client.request(method, path, headers=COOKIE | {"X-CSRF-Protection": "1"})

    assert response.status_code != 403


async def test_safe_request_with_cookie_does_not_need_header(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/auth/me", headers=COOKIE)

    assert response.status_code == 401


async def test_request_without_cookie_is_not_checked(db_client: AsyncClient) -> None:
    # Так будут ходить MCP и скрипты: с Authorization: Bearer, без cookie.
    response = await db_client.post(
        "/api/v1/auth/login", json={"email": "student@example.com", "password": "password1"}
    )

    assert response.status_code == 401
