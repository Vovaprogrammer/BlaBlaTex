"""Свой ключ LLM (architecture.md 5, 9.1): проверка у провайдера, шифрование, только сайт,
наружу — последние 4 символа. Провайдер — только мок httpx."""

import asyncio
import json
import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.auth import dependencies as auth_dependencies
from app.modules.llm import router, service
from app.modules.llm.dependencies import get_key_check
from app.modules.llm.models import LlmKey
from app.scripts import rotate_llm_keys
from tests.fake_rate_limiter import FakeRateLimiter
from tests.helpers import TEMPLATE_FIXTURES
from tests.live_builds import Live
from tests.llm_settings import (
    BASE_URL,
    ENCRYPTION_KEY,
    MAIN_MODEL,
    OTHER_ENCRYPTION_KEY,
    PROVIDER,
    STUDENT_KEY,
    llm_settings,
    store_key,
)
from tests.test_bearer_auth import issue_token, use_token

API = "/api/v1"
URL = f"{API}/settings/llm-key"
# Any — JSON ответа API.
Json = dict[str, Any]
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Настройки приложения тестов — с провайдером и шифрованием своих ключей."""
    return llm_settings(storage_dir=tmp_path / "storage", templates_dir=TEMPLATE_FIXTURES)


class Provider:
    """Провайдер LLM на моке httpx: отвечает статусом и запоминает запросы."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"choices": []})


@pytest.fixture
def provider(app: FastAPI) -> Provider:
    fake = Provider()
    use_provider(app, fake)
    return fake


def use_provider(app: FastAPI, handler: Handler | httpx.AsyncBaseTransport) -> None:
    transport = (
        handler if isinstance(handler, httpx.AsyncBaseTransport) else httpx.MockTransport(handler)
    )
    app.dependency_overrides[get_key_check] = lambda: partial(
        service.check_key, transport=transport
    )


async def put_key(client: AsyncClient, key: str = STUDENT_KEY) -> httpx.Response:
    return await client.put(URL, json={"key": key})


async def stored(session: AsyncSession) -> list[LlmKey]:
    rows = await session.scalars(select(LlmKey).execution_options(populate_existing=True))
    return list(rows)


async def test_no_key_yet_shows_which_provider_needs_it(
    user_client: AsyncClient, provider: Provider
) -> None:
    response = await user_client.get(URL)

    assert response.status_code == 200
    assert response.json() == {"provider": PROVIDER, "key": None}


async def test_saved_key_is_checked_encrypted_and_shown_by_last4(
    user_client: AsyncClient, db_session: AsyncSession, provider: Provider
) -> None:
    response = await put_key(user_client, f"  {STUDENT_KEY}\n")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["provider"], body["last4"]) == (PROVIDER, STUDENT_KEY[-4:])
    assert STUDENT_KEY not in response.text
    # Пробный запрос — к основной модели провайдера из настроек, ответ в 1 токен.
    [request] = provider.requests
    assert str(request.url) == f"{BASE_URL}/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {STUDENT_KEY}"
    sent = json.loads(request.content)
    assert (sent["model"], sent["max_tokens"]) == (MAIN_MODEL, 1)
    # В базе — только шифр.
    [row] = await stored(db_session)
    assert STUDENT_KEY not in row.encrypted_key
    assert Fernet(ENCRYPTION_KEY).decrypt(row.encrypted_key.encode()).decode() == STUDENT_KEY
    shown = (await user_client.get(URL)).json()
    assert shown == {"provider": PROVIDER, "key": body}


async def test_new_key_replaces_old_one(
    user_client: AsyncClient, db_session: AsyncSession, provider: Provider
) -> None:
    await put_key(user_client)
    newer = "sk-or-v1-ffffffffffffffffffffffffffff9999"

    response = await put_key(user_client, newer)

    assert response.json()["last4"] == "9999"
    [row] = await stored(db_session)
    assert row.last4 == "9999"


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("short", service.KEY_LENGTH_MESSAGE),
        ("x" * (service.KEY_MAX_LENGTH + 1), service.KEY_LENGTH_MESSAGE),
        ("sk-or-v1 0123456789", service.KEY_FORMAT_MESSAGE),
        ("sk-or-v1-ключ-0123456789", service.KEY_FORMAT_MESSAGE),
        ("sk-or-v1-0123\t456789", service.KEY_FORMAT_MESSAGE),
    ],
    ids=["short", "long", "space", "cyrillic", "tab"],
)
async def test_malformed_key_is_rejected_without_asking_provider(
    user_client: AsyncClient,
    db_session: AsyncSession,
    provider: Provider,
    key: str,
    message: str,
) -> None:
    response = await put_key(user_client, key)

    assert response.status_code == 422
    [error] = response.json()["error"]["details"]["errors"]
    assert (error["loc"], error["message"]) == (["body", "key"], message)
    assert key not in response.text
    assert provider.requests == []
    assert await stored(db_session) == []


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (401, 422, service.KEY_REJECTED_MESSAGE),
        (403, 422, service.KEY_REJECTED_MESSAGE),
        (402, 422, service.KEY_NO_FUNDS_MESSAGE),
        (500, 500, service.KEY_UNAVAILABLE_MESSAGE),
        (503, 500, service.KEY_UNAVAILABLE_MESSAGE),
    ],
)
async def test_key_refused_by_provider_is_not_saved(
    user_client: AsyncClient,
    db_session: AsyncSession,
    provider: Provider,
    status: int,
    code: int,
    message: str,
) -> None:
    provider.status = status

    response = await put_key(user_client)

    assert response.status_code == code
    error = response.json()["error"]
    if code == 422:
        assert error["details"]["errors"][0]["message"] == message
    else:
        assert (error["code"], error["message"]) == ("internal", message)
    assert await stored(db_session) == []


@pytest.mark.parametrize("status", [200, 400, 404, 429])
async def test_key_accepted_by_provider_is_saved(
    user_client: AsyncClient, db_session: AsyncSession, provider: Provider, status: int
) -> None:
    # 429 — провайдер перегружен, 400 и 404 — ему не понравился запрос: ключ он принял.
    provider.status = status

    response = await put_key(user_client)

    assert response.status_code == 200
    assert len(await stored(db_session)) == 1


async def test_silent_or_unreachable_provider_means_key_not_checked(
    app: FastAPI,
    user_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "KEY_CHECK_TIMEOUT_S", 0.05)

    async def silent(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет связи", request=request)

    for handler in (silent, unreachable):
        use_provider(app, httpx.MockTransport(handler))
        response = await put_key(user_client)
        assert response.status_code == 500
        assert response.json()["error"]["message"] == service.KEY_UNAVAILABLE_MESSAGE
    assert await stored(db_session) == []


async def test_key_never_reaches_logs(user_client: AsyncClient, provider: Provider) -> None:
    with structlog.testing.capture_logs() as logs:
        await put_key(user_client)
        provider.status = 401
        await put_key(user_client)

    assert any(log["event"] == "llm_key_saved" for log in logs)
    assert STUDENT_KEY not in repr(logs)


async def test_attempts_are_rate_limited_per_user(
    user_client: AsyncClient, provider: Provider, rate_limits: FakeRateLimiter
) -> None:
    rate_limits.retry_after = 600

    response = await put_key(user_client)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    [check] = rate_limits.checks
    assert (check.name, check.limit) == ("llm_key_save", router.LLM_KEY_SAVE_LIMIT)
    assert provider.requests == []


async def test_delete_removes_key_and_repeats_quietly(
    user_client: AsyncClient, db_session: AsyncSession, provider: Provider
) -> None:
    await put_key(user_client)

    first = await user_client.delete(URL)
    second = await user_client.delete(URL)

    assert (first.status_code, second.status_code) == (204, 204)
    assert await stored(db_session) == []
    assert (await user_client.get(URL)).json()["key"] is None


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_key_is_managed_only_on_site(
    user_client: AsyncClient, provider: Provider, method: str
) -> None:
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    response = await user_client.request(
        method, URL, json={"key": STUDENT_KEY} if method == "PUT" else None
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == auth_dependencies.BROWSER_ONLY_MESSAGE
    assert provider.requests == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"app_encryption_key": None}, service.ENCRYPTION_MISSING_MESSAGE),
        (
            {"llm_providers": {}, "llm_default_provider": None},
            service.LLM_NOT_CONFIGURED_MESSAGE,
        ),
    ],
    ids=["no-encryption", "no-llm"],
)
async def test_key_cannot_be_saved_without_server_setup(
    app: FastAPI,
    user_client: AsyncClient,
    provider: Provider,
    overrides: dict[str, Any],
    message: str,
) -> None:
    app.state.settings = llm_settings(**overrides)

    response = await put_key(user_client)

    assert response.status_code == 500
    assert response.json()["error"]["message"] == message
    assert provider.requests == []


async def test_without_llm_settings_show_no_provider(
    app: FastAPI, user_client: AsyncClient
) -> None:
    app.state.settings = llm_settings(llm_providers={}, llm_default_provider=None)

    assert (await user_client.get(URL)).json() == {"provider": None, "key": None}


# --- Какой ключ берут прогон и описание картинки ---


async def owner(user_client: AsyncClient) -> uuid.UUID:
    me = (await user_client.get(f"{API}/auth/me")).json()
    return uuid.UUID(me["user"]["id"])


async def test_usable_key_is_decrypted(user_client: AsyncClient, db_session: AsyncSession) -> None:
    user_id = await owner(user_client)
    settings = llm_settings()
    await store_key(db_session, user_id, settings)

    key = await service.usable_key(db_session, user_id, settings)

    assert key is not None
    assert key.get_secret_value() == STUDENT_KEY
    assert STUDENT_KEY not in repr(key)


async def test_no_usable_key_without_saved_one(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    assert await service.usable_key(db_session, await owner(user_client), llm_settings()) is None


async def test_key_for_previous_provider_is_not_used(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id = await owner(user_client)
    await store_key(db_session, user_id, llm_settings())

    # Основным провайдером сервиса стал другой: ключ OpenRouter туда не отправляем.
    switched = llm_settings(llm_default_provider="backup", llm_fallback_provider=PROVIDER)

    assert await service.usable_key(db_session, user_id, switched) is None


async def test_undecryptable_key_is_not_used(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id = await owner(user_client)
    await store_key(db_session, user_id, llm_settings())
    # Прежний ключ шифрования убрали раньше, чем перешифровали ключи студентов.
    other = llm_settings(app_encryption_key=SecretStr(OTHER_ENCRYPTION_KEY))

    with structlog.testing.capture_logs() as logs:
        key = await service.usable_key(db_session, user_id, other)

    assert key is None
    assert [log["event"] for log in logs] == ["llm_key_undecryptable"]


async def test_rotation_moves_keys_to_new_encryption_key(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id = await owner(user_client)
    await store_key(db_session, user_id, llm_settings())
    # Шаг 1: новый ключ шифрования — первым, старый ещё расшифровывает.
    both = llm_settings(app_encryption_key=SecretStr(f"{OTHER_ENCRYPTION_KEY},{ENCRYPTION_KEY}"))
    assert await service.usable_key(db_session, user_id, both) is not None

    rotated = await service.rotate_keys(db_session, both)

    # Шаг 2: старый ключ убран — ключ студента по-прежнему читается.
    only_new = llm_settings(app_encryption_key=SecretStr(OTHER_ENCRYPTION_KEY))
    key = await service.usable_key(db_session, user_id, only_new)
    assert rotated == (1, 0)
    assert key is not None
    assert key.get_secret_value() == STUDENT_KEY


async def test_rotation_script_rewrites_saved_keys(live: Live, db_settings: Settings) -> None:
    async with live.sessionmaker() as session:
        await store_key(session, live.owner_id, llm_settings())
    both = db_settings.model_copy(
        update={"app_encryption_key": SecretStr(f"{OTHER_ENCRYPTION_KEY},{ENCRYPTION_KEY}")}
    )

    rotated, undecryptable = await rotate_llm_keys.rotate(both)

    assert (rotated >= 1, undecryptable) == (True, 0)
    only_new = llm_settings(app_encryption_key=SecretStr(OTHER_ENCRYPTION_KEY))
    async with live.sessionmaker() as session:
        key = await service.usable_key(session, live.owner_id, only_new)
    assert key is not None
    assert key.get_secret_value() == STUDENT_KEY
