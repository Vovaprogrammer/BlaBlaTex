"""Личные токены: создание, список и удаление через HTTP, на тестовой базе (9.1)."""

import hashlib
import string
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service
from app.modules.auth.models import ApiToken, User
from tests.helpers import CSRF, STUDENT_EMAIL, SignUp

TOKENS = "/api/v1/tokens"


async def create(client: AsyncClient, name: str | None = None) -> dict[str, object]:
    body = {} if name is None else {"name": name}
    response = await client.post(TOKENS, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def names(client: AsyncClient) -> list[str]:
    response = await client.get(TOKENS)
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["items"]]


async def backdate(session: AsyncSession, token_id: object, days: int) -> None:
    """Токен создан days дней назад и с тех пор им не пользовались."""
    created = datetime.now(UTC) - timedelta(days=days)
    await session.execute(
        update(ApiToken)
        .where(ApiToken.id == uuid.UUID(str(token_id)))
        .values(created_at=created, last_used_at=None)
    )
    await session.commit()


def test_token_is_prefix_and_43_base62_chars() -> None:
    alphabet = set(string.digits + string.ascii_letters)
    tokens = {service.generate_api_token() for _ in range(200)}

    assert len(tokens) == 200
    for token in tokens:
        assert token.startswith("bbt_pat_")
        body = token.removeprefix("bbt_pat_")
        assert len(body) == 43
        assert set(body) <= alphabet


@pytest.mark.parametrize("random", [b"\x00" * 32, b"\xff" * 32])
def test_token_length_does_not_depend_on_random_bytes(
    monkeypatch: pytest.MonkeyPatch, random: bytes
) -> None:
    monkeypatch.setattr(service.secrets, "token_bytes", lambda _: random)

    token = service.generate_api_token()

    assert len(token) == len("bbt_pat_") + 43
    if random[0] == 0:
        assert token == "bbt_pat_" + "0" * 43


async def test_token_value_is_shown_only_once(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await create(user_client, "Codex на ноутбуке")

    assert set(created) == {"id", "name", "created_at", "last_used_at", "token"}
    assert created["name"] == "Codex на ноутбуке"
    assert created["last_used_at"] is None
    token = str(created["token"])
    listed = (await user_client.get(TOKENS)).json()["items"]
    assert listed == [{key: created[key] for key in ("id", "name", "created_at", "last_used_at")}]
    # В базе — только sha256, значения нет ни в одном поле.
    row = await db_session.get(ApiToken, uuid.UUID(str(created["id"])))
    assert row is not None
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in {row.name, row.token_hash}


async def test_name_is_optional_and_numbered(user_client: AsyncClient) -> None:
    first = await create(user_client)
    await create(user_client, "  Claude Code  ")
    third = await create(user_client)
    await user_client.delete(f"{TOKENS}/{first['id']}")
    fourth = (await user_client.post(TOKENS, json={"name": None})).json()

    assert first["name"] == "Токен 1"
    assert third["name"] == "Токен 3"
    # Номер — сколько токенов создано, считая удалённые: подписи не повторяются.
    assert fourth["name"] == "Токен 4"
    assert await names(user_client) == ["Токен 4", "Токен 3", "Claude Code"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, "a\x00b"])
async def test_bad_name_is_422(user_client: AsyncClient, name: str) -> None:
    response = await user_client.post(TOKENS, json={"name": name})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["errors"][0]["loc"] == ["body", "name"]


async def test_list_shows_only_own_working_tokens(
    user_client: AsyncClient, sign_up: SignUp, db_session: AsyncSession
) -> None:
    await create(user_client, "старый")
    idle = await create(user_client, "брошенный")
    await create(user_client, "рабочий")
    await backdate(db_session, idle["id"], days=91)
    removed = await create(user_client, "удалённый")
    await user_client.delete(f"{TOKENS}/{removed['id']}")

    assert await names(user_client) == ["рабочий", "старый"]
    await sign_up("other@example.com")
    assert await names(user_client) == []


async def test_token_used_recently_does_not_expire(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await create(user_client, "старый, но живой")
    old = datetime.now(UTC) - timedelta(days=200)
    await db_session.execute(
        update(ApiToken)
        .where(ApiToken.id == uuid.UUID(str(created["id"])))
        .values(created_at=old, last_used_at=datetime.now(UTC) - timedelta(days=89))
    )
    await db_session.commit()

    assert await names(user_client) == ["старый, но живой"]


async def test_delete_stops_token_and_second_delete_is_404(user_client: AsyncClient) -> None:
    created = await create(user_client)

    first = await user_client.delete(f"{TOKENS}/{created['id']}")
    second = await user_client.delete(f"{TOKENS}/{created['id']}")

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.json()["error"] == {
        "code": "not_found",
        "message": "Токен не найден",
        "details": {},
    }
    assert await names(user_client) == []


async def test_cannot_delete_foreign_unknown_or_idle_token(
    user_client: AsyncClient, sign_up: SignUp, db_session: AsyncSession
) -> None:
    idle = await create(user_client)
    await backdate(db_session, idle["id"], days=91)
    foreign = await create(user_client)
    await sign_up("other@example.com")
    user_client.headers.update(CSRF)

    for token_id in (foreign["id"], idle["id"], uuid.uuid4()):
        response = await user_client.delete(f"{TOKENS}/{token_id}")
        assert response.status_code == 404, token_id
    revoked = await db_session.scalar(
        select(func.count()).select_from(ApiToken).where(ApiToken.revoked_at.is_not(None))
    )
    assert revoked == 0


async def test_at_most_20_working_tokens(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    created = [await create(user_client) for _ in range(20)]

    refused = await user_client.post(TOKENS, json={})
    await user_client.delete(f"{TOKENS}/{created[0]['id']}")
    after_delete = await user_client.post(TOKENS, json={})
    await backdate(db_session, created[1]["id"], days=91)
    after_idle = await user_client.post(TOKENS, json={})

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden"
    assert refused.json()["error"]["message"] == service.TOO_MANY_TOKENS_MESSAGE
    assert after_delete.status_code == 201
    # Отключённый по сроку токен тоже не занимает место.
    assert after_idle.status_code == 201
    assert len(await names(user_client)) == 20


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", TOKENS), ("POST", TOKENS), ("DELETE", f"{TOKENS}/{uuid.uuid4()}")],
)
async def test_tokens_need_sign_in(db_client: AsyncClient, method: str, path: str) -> None:
    response = await db_client.request(method, path, json={} if method == "POST" else None)

    assert response.status_code == 401


async def test_deleting_user_deletes_tokens(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    await create(user_client)

    await db_session.execute(delete(User).where(User.email == STUDENT_EMAIL))
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(ApiToken)) == 0
