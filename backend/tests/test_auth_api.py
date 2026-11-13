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
from app.modules.auth.dependencies import PROD_SESSION_COOKIE
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


async def test_register_records_consent_time(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    before = datetime.now(UTC)

    await register(db_client)

    user = (await db_session.scalars(select(User))).one()
    assert before <= user.consent_at <= datetime.now(UTC)


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


async def test_authenticated_response_extends_cookie(db_client: AsyncClient) -> None:
    token = session_cookie(await register(db_client)).value

    response = await me(db_client)

    cookie = session_cookie(response)
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


async def test_prod_session_cookie_has_host_prefix(
    app: FastAPI, db_client: AsyncClient, settings: Settings
) -> None:
    app.state.settings = settings.model_copy(update={"app_env": "prod"})

    response = await register(db_client)

    [header] = response.headers.get_list("set-cookie")
    assert header.startswith(f"{PROD_SESSION_COOKIE}=")
    cookie = SimpleCookie(header)[PROD_SESSION_COOKIE]
    # Без этих флагов браузер не примет cookie с приставкой __Host-.
    assert cookie["secure"] is True
    assert cookie["path"] == "/"
    assert cookie["domain"] == ""
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["max-age"] == str(int(SESSION_TTL.total_seconds()))


async def test_local_install_cookie_works_over_http(
    app: FastAPI, db_client: AsyncClient, settings: Settings
) -> None:
    # Установка у студента: сайт на http://localhost, а Safari там Secure-cookie не примет.
    app.state.settings = settings.model_copy(update={"app_env": "local"})

    response = await register(db_client)

    [header] = response.headers.get_list("set-cookie")
    cookie = SimpleCookie(header)["bbt_session"]
    assert cookie["secure"] == ""
    assert cookie["httponly"] is True
    assert (await db_client.get(f"{AUTH}/me")).status_code == 200


async def test_prod_reads_only_cookie_with_host_prefix(
    app: FastAPI, db_client: AsyncClient, settings: Settings
) -> None:
    app.state.settings = settings.model_copy(update={"app_env": "prod"})
    [header] = (await register(db_client)).headers.get_list("set-cookie")
    token = SimpleCookie(header)[PROD_SESSION_COOKIE].value
    # Secure-cookie клиент по http не отправит — заголовок Cookie задаём сами.
    db_client.cookies.clear()
    prod_cookie = {"Cookie": f"{PROD_SESSION_COOKIE}={token}"}

    me_prod = await db_client.get(f"{AUTH}/me", headers=prod_cookie)
    me_old_name = await db_client.get(f"{AUTH}/me", headers={"Cookie": f"bbt_session={token}"})
    # Защита от CSRF смотрит на cookie с новым именем.
    no_csrf = await db_client.post(f"{AUTH}/logout", headers=prod_cookie)
    logout = await db_client.post(
        f"{AUTH}/logout", headers={**prod_cookie, "X-CSRF-Protection": "1"}
    )

    assert me_prod.status_code == 200
    assert me_old_name.status_code == 401
    assert no_csrf.status_code == 403
    assert logout.status_code == 204
    deleted = SimpleCookie(logout.headers["set-cookie"])[PROD_SESSION_COOKIE]
    assert deleted["max-age"] == "0"
    assert deleted["secure"] is True
    assert deleted["path"] == "/"
