"""Профиль текущего пользователя: GET/PUT /profile и профиль в /auth/me."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.profiles.schemas import ProfileUpdate

PROFILE_URL = "/api/v1/profile"
CSRF = {"X-CSRF-Protection": "1"}
EMPTY = dict.fromkeys(ProfileUpdate.model_fields, "")
IVANOV = {
    "last_name": "Иванов",
    "first_name": "Иван",
    "middle_name": "Иванович",
    "group_name": "БВТ2401",
    "faculty": "Информационные технологии",
    "department": "Математическая кибернетика",
}


async def sign_up(client: AsyncClient, email: str) -> None:
    client.cookies.clear()
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password1", "consent": True}
    )
    assert response.status_code == 201


def fields(profile: dict[str, Any]) -> dict[str, Any]:  # Any — значения из JSON ответа
    return {k: v for k, v in profile.items() if k != "updated_at"}


async def test_new_user_has_empty_profile(db_client: AsyncClient) -> None:
    await sign_up(db_client, "student@example.com")

    response = await db_client.get(PROFILE_URL)

    assert response.status_code == 200
    assert fields(response.json()) == EMPTY
    me = await db_client.get("/api/v1/auth/me")
    assert me.json()["profile"] == response.json()


async def test_put_replaces_whole_profile(db_client: AsyncClient) -> None:
    await sign_up(db_client, "student@example.com")
    await db_client.put(PROFILE_URL, json=IVANOV, headers=CSRF)
    changed = IVANOV | {"middle_name": "", "group_name": "БВТ2402"}

    response = await db_client.put(PROFILE_URL, json=changed, headers=CSRF)

    assert response.status_code == 200
    assert fields(response.json()) == changed
    saved = await db_client.get(PROFILE_URL)
    assert saved.json() == response.json()


@pytest.mark.parametrize(("method", "kwargs"), [("GET", {}), ("PUT", {"json": IVANOV})])
async def test_profile_requires_sign_in(
    db_client: AsyncClient,
    method: str,
    kwargs: dict[str, Any],  # Any — kwargs для httpx
) -> None:
    response = await db_client.request(method, PROFILE_URL, **kwargs)

    assert response.status_code == 401


async def test_user_sees_only_own_profile(db_client: AsyncClient) -> None:
    await sign_up(db_client, "ivanov@example.com")
    await db_client.put(PROFILE_URL, json=IVANOV, headers=CSRF)

    await sign_up(db_client, "petrov@example.com")
    profile = await db_client.get(PROFILE_URL)
    me = await db_client.get("/api/v1/auth/me")

    assert fields(profile.json()) == EMPTY
    assert fields(me.json()["profile"]) == EMPTY
