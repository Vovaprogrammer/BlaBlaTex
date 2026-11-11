"""Вход по личному токену: Authorization: Bearer bbt_pat_… рядом с cookie сессии (9.1)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import Limit, RedisRateLimiter
from app.modules.auth import dependencies
from app.modules.auth.models import ApiToken
from tests.fake_rate_limiter import FakeRateLimiter, RateCheck
from tests.helpers import CSRF, STUDENT_EMAIL, TEST_TEMPLATES, CreateProject, SignUp

API = "/api/v1"
Json = dict[str, Any]


async def issue_token(client: AsyncClient) -> Json:
    """Токен текущего пользователя, созданный на сайте (по cookie)."""
    response = await client.post(f"{API}/tokens", json={}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def use_token(client: AsyncClient, token: str) -> None:
    """Дальше клиент ходит как агент: только с токеном, без cookie и CSRF-заголовка."""
    client.cookies.clear()
    client.headers.pop("X-CSRF-Protection", None)
    client.headers["Authorization"] = f"Bearer {token}"


async def last_used(session: AsyncSession, token: Json) -> datetime | None:
    row = await session.get(ApiToken, uuid.UUID(token["id"]), populate_existing=True)
    assert row is not None
    return row.last_used_at


async def test_agent_works_with_token_alone(
    user_client: AsyncClient, create_project: CreateProject
) -> None:
    project = await create_project()
    use_token(user_client, (await issue_token(user_client))["token"])
    files = f"{API}/projects/{project['id']}/files"

    me = await user_client.get(f"{API}/auth/me")
    created = await user_client.post(
        f"{API}/projects",
        json={"title": "ЛР 2", "template_slug": "test-lab", "fields": TEST_TEMPLATES["test-lab"]},
    )
    written = await user_client.put(
        f"{files}/notes.tex", content="Текст агента", headers={"If-None-Match": "*"}
    )
    uploaded = await user_client.post(
        f"{API}/projects/{project['id']}/upload",
        files=[("files", ("code.py", b"print(1)\n"))],
        data={"dir": "materials"},
    )

    assert me.status_code == 200
    assert me.json()["user"]["email"] == STUDENT_EMAIL
    assert created.status_code == 201, created.text
    assert written.status_code == 201, written.text
    assert uploaded.status_code == 200, uploaded.text
    # Агенту cookie не нужна, и сервер её не ставит.
    assert "set-cookie" not in me.headers


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("bbt_pat_" + "0" * 43, dependencies.TOKEN_MESSAGES["unknown"]),
        ("not-a-token", dependencies.TOKEN_MESSAGES["unknown"]),
        ("", dependencies.TOKEN_MESSAGES["unknown"]),
    ],
)
async def test_wrong_token_is_401_with_hint(
    db_client: AsyncClient, token: str, message: str
) -> None:
    response = await db_client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"] == {"code": "unauthorized", "message": message, "details": {}}


async def test_deleted_token_is_401_with_hint(user_client: AsyncClient) -> None:
    token = await issue_token(user_client)
    await user_client.delete(f"{API}/tokens/{token['id']}")
    use_token(user_client, token["token"])

    response = await user_client.get(f"{API}/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == dependencies.TOKEN_MESSAGES["revoked"]


async def test_idle_token_is_401_with_hint(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await issue_token(user_client)
    await db_session.execute(
        update(ApiToken)
        .where(ApiToken.id == uuid.UUID(token["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(days=90, minutes=1))
    )
    await db_session.commit()
    use_token(user_client, token["token"])

    response = await user_client.get(f"{API}/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["message"].startswith("Токеном не пользовались 90 дней")


async def test_token_wins_over_cookie(user_client: AsyncClient, sign_up: SignUp) -> None:
    token = (await issue_token(user_client))["token"]
    await sign_up("other@example.com")
    auth = {"Authorization": f"Bearer {token}"}

    me = await user_client.get(f"{API}/auth/me", headers=auth)
    wrong = await user_client.get(
        f"{API}/auth/me", headers={"Authorization": "Bearer bbt_pat_wrong"}
    )

    assert me.json()["user"]["email"] == STUDENT_EMAIL
    # С неверным токеном вход по cookie не пробуется: агент должен узнать, что токен плохой.
    assert wrong.status_code == 401


async def test_unsafe_request_with_token_and_cookie_needs_no_csrf_header(
    user_client: AsyncClient,
) -> None:
    token = (await issue_token(user_client))["token"]
    user_client.headers.pop("X-CSRF-Protection", None)

    without_token = await user_client.post(f"{API}/tokens", json={})
    with_token = await user_client.put(
        f"{API}/profile",
        json={"last_name": "Иванов"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert without_token.status_code == 403
    assert without_token.json()["error"]["message"] == dependencies.CSRF_MESSAGE
    assert with_token.status_code != 403, with_token.text


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/tokens"), ("POST", "/tokens"), ("DELETE", "/tokens/{tid}")],
)
async def test_tokens_are_managed_only_on_site(
    user_client: AsyncClient, method: str, path: str
) -> None:
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    response = await user_client.request(
        method, API + path.format(tid=token["id"]), json={} if method == "POST" else None
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == dependencies.BROWSER_ONLY_MESSAGE


async def test_last_used_at_is_written_once_per_interval(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    await user_client.get(f"{API}/auth/me")
    first = await last_used(db_session, token)
    await user_client.get(f"{API}/auth/me")
    second = await last_used(db_session, token)
    hour_ago = datetime.now(UTC) - timedelta(hours=1, minutes=1)
    await db_session.execute(
        update(ApiToken).where(ApiToken.id == uuid.UUID(token["id"])).values(last_used_at=hour_ago)
    )
    await db_session.commit()
    await user_client.get(f"{API}/auth/me")
    third = await last_used(db_session, token)

    assert first is not None
    assert second == first
    assert third is not None and third > hour_ago


async def test_only_token_requests_are_rate_limited(
    user_client: AsyncClient, rate_limits: FakeRateLimiter
) -> None:
    token = await issue_token(user_client)
    await user_client.get(f"{API}/auth/me")
    assert rate_limits.checks == []

    use_token(user_client, token["token"])
    await user_client.get(f"{API}/auth/me")

    assert rate_limits.checks == [
        RateCheck("api_token", token["id"], Limit(count=120, period_s=60))
    ]


async def test_token_over_limit_gets_429_and_other_token_works(
    app: FastAPI,
    user_client: AsyncClient,
    rate_limiter: RedisRateLimiter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dependencies, "API_TOKEN_LIMIT", Limit(count=2, period_s=60))
    app.state.rate_limiter = rate_limiter
    busy = (await issue_token(user_client))["token"]
    other = (await issue_token(user_client))["token"]
    use_token(user_client, busy)

    statuses = [(await user_client.get(f"{API}/auth/me")).status_code for _ in range(2)]
    refused = await user_client.get(f"{API}/auth/me")
    use_token(user_client, other)
    other_response = await user_client.get(f"{API}/auth/me")

    assert statuses == [200, 200]
    assert refused.status_code == 429
    error = refused.json()["error"]
    assert error["code"] == "rate_limited"
    assert refused.headers["retry-after"] == str(error["details"]["retry_after"])
    assert 1 <= error["details"]["retry_after"] <= 60
    assert other_response.status_code == 200


async def test_token_edits_are_mcp_changesets(
    user_client: AsyncClient, create_project: CreateProject, db_session: AsyncSession
) -> None:
    project = await create_project()
    files = f"{API}/projects/{project['id']}/files"
    token = (await issue_token(user_client))["token"]
    by_site = await user_client.put(
        f"{files}/site.tex", content="студент", headers={"If-None-Match": "*"}
    )
    use_token(user_client, token)
    by_agent = await user_client.put(
        f"{files}/agent.tex", content="агент", headers={"If-None-Match": "*"}
    )

    changesets = (await user_client.get(f"{API}/projects/{project['id']}/changesets")).json()

    assert by_site.status_code == by_agent.status_code == 201
    # Правка агента не склеилась с правкой студента: её откатывают отдельно.
    authors = [item["author"] for item in changesets["items"]]
    assert authors[:2] == ["mcp", "user"]
    used = await db_session.scalar(select(ApiToken.last_used_at))
    assert used is not None
