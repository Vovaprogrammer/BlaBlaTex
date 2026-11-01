"""Регистрация, вход, выход и текущий пользователь через HTTP, на тестовой базе."""

from datetime import UTC, datetime, timedelta
from http.cookies import Morsel, SimpleCookie

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.auth.models import User, UserSession
from app.modules.auth.service import SESSION_TTL
from app.modules.profiles import service as profiles_service
from app.modules.profiles.schemas import ProfileUpdate

AUTH = "/api/v1/auth"
EMAIL = "student@example.com"
PASSWORD = "password1"
EMPTY_PROFILE = dict.fromkeys(ProfileUpdate.model_fields, "")


async def register(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    return await client.post(
        f"{AUTH}/register", json={"email": email, "password": password, "consent": True}
    )


async def login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    return await client.post(f"{AUTH}/login", json={"email": email, "password": password})


async def me(client: AsyncClient, token: str | None = None) -> Response:
    # Явный заголовок Cookie вместо cookie клиента — чтобы проверить конкретный токен.
    headers = {"Cookie": f"bbt_session={token}"} if token else {}
    return await client.get(f"{AUTH}/me", headers=headers)


def session_cookie(response: Response) -> Morsel[str]:
    [header] = response.headers.get_list("set-cookie")
    return SimpleCookie(header)["bbt_session"]


async def count(session: AsyncSession, model: type[User | UserSession]) -> int | None:
    return await session.scalar(select(func.count()).select_from(model))


async def test_register_signs_in_with_session_cookie(db_client: AsyncClient) -> None:
    response = await register(db_client, email="Student@Example.COM")

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == EMAIL
    assert body["user"]["role"] == "student"
    assert {k: body["profile"][k] for k in EMPTY_PROFILE} == EMPTY_PROFILE
    cookie = session_cookie(response)
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["max-age"] == str(int(SESSION_TTL.total_seconds()))
    assert cookie["path"] == "/"
    assert not cookie["secure"]


async def test_me_returns_signed_in_user(db_client: AsyncClient) -> None:
    user = (await register(db_client)).json()["user"]

    response = await me(db_client)

    assert response.status_code == 200
    assert response.json()["user"] == user


@pytest.mark.parametrize("token", [None, "not-a-token"], ids=["no cookie", "unknown token"])
async def test_me_without_valid_session_is_unauthorized(
    db_client: AsyncClient, token: str | None
) -> None:
    response = await me(db_client, token)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("consent", [False, 1, 1.0, "true"])
async def test_register_requires_explicit_consent(db_client: AsyncClient, consent: object) -> None:
    response = await db_client.post(
        f"{AUTH}/register", json={"email": EMAIL, "password": PASSWORD, "consent": consent}
    )

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(["body", "consent"], "literal_error")]


async def test_register_rejects_short_password_and_bad_email(db_client: AsyncClient) -> None:
    response = await register(db_client, email="not-an-email", password="short")

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [
        (["body", "email"], "value_error"),
        (["body", "password"], "string_too_short"),
    ]


async def test_register_rejects_taken_email_in_any_case(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(db_client)
    db_client.cookies.clear()

    response = await register(db_client, email="STUDENT@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_exists"
    assert "set-cookie" not in response.headers
    assert await count(db_session, User) == 1


async def test_login_accepts_email_in_any_case(db_client: AsyncClient) -> None:
    await register(db_client)
    db_client.cookies.clear()

    response = await login(db_client, email="Student@Example.com")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == EMAIL
    assert (await me(db_client, session_cookie(response).value)).status_code == 200


async def test_login_rejects_wrong_password_and_unknown_email_alike(
    db_client: AsyncClient,
) -> None:
    await register(db_client)
    db_client.cookies.clear()

    wrong_password = await login(db_client, password="password2")
    unknown_email = await login(db_client, email="other@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["error"]["code"] == "unauthorized"
    assert "set-cookie" not in wrong_password.headers


async def test_login_upgrades_outdated_password_hash(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    old_hash = Argon2Hasher(time_cost=1).hash(PASSWORD)
    user = User(email=EMAIL, password_hash=old_hash, consent_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    profiles_service.create_empty_profile(db_session, user.id)

    response = await login(db_client)

    assert response.status_code == 200
    assert user.password_hash != old_hash


async def test_expired_session_is_unauthorized(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(db_client)
    expired = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.execute(update(UserSession).values(expires_at=expired))

    response = await me(db_client)

    assert response.status_code == 401


async def test_session_renewal_reissues_cookie(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = session_cookie(await register(db_client)).value
    fresh = await me(db_client)
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(update(UserSession).values(last_seen_at=two_hours_ago))

    renewed = await me(db_client)

    assert "set-cookie" not in fresh.headers
    cookie = session_cookie(renewed)
    assert cookie.value == token
    assert cookie["max-age"] == str(int(SESSION_TTL.total_seconds()))


async def test_logout_ends_session(db_client: AsyncClient, db_session: AsyncSession) -> None:
    token = session_cookie(await register(db_client)).value

    response = await db_client.post(f"{AUTH}/logout", headers={"X-CSRF-Protection": "1"})

    assert response.status_code == 204
    assert session_cookie(response)["max-age"] == "0"
    assert await count(db_session, UserSession) == 0
    # Даже если браузер не удалил cookie, старый токен больше не работает.
    assert (await me(db_client, token)).status_code == 401


async def test_logout_without_session_succeeds(db_client: AsyncClient) -> None:
    response = await db_client.post(f"{AUTH}/logout")

    assert response.status_code == 204


async def test_session_cookie_is_secure_in_prod(
    app: FastAPI, db_client: AsyncClient, settings: Settings
) -> None:
    app.state.settings = settings.model_copy(update={"app_env": "prod"})

    response = await register(db_client)

    assert session_cookie(response)["secure"] is True
