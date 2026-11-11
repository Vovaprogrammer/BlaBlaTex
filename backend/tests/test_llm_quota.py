"""Дневная квота (architecture.md 8, 9.1): GET /usage, 429 перед прогоном, свой ключ квоту не
тратит, описание картинки пропускается, когда квоты нет."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.chat.dependencies import get_run_enqueue
from app.modules.chat.models import AgentRun, ChatMessage
from app.modules.llm import service
from tests.helpers import TEMPLATE_FIXTURES
from tests.llm_settings import llm_settings, store_key
from tests.test_bearer_auth import issue_token, use_token

API = "/api/v1"
LIMIT = 1000
# Any — JSON проекта из API.
Project = dict[str, Any]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Настройки приложения тестов — с маленьким лимитом, провайдером и шифрованием."""
    return llm_settings(
        storage_dir=tmp_path / "storage",
        templates_dir=TEMPLATE_FIXTURES,
        llm_daily_token_limit=LIMIT,
    )


@pytest.fixture
def enqueued(app: FastAPI) -> list[uuid.UUID]:
    run_ids: list[uuid.UUID] = []

    async def enqueue(run_id: uuid.UUID) -> None:
        run_ids.append(run_id)

    app.dependency_overrides[get_run_enqueue] = lambda: enqueue
    return run_ids


async def owner(client: AsyncClient) -> uuid.UUID:
    me = (await client.get(f"{API}/auth/me")).json()
    return uuid.UUID(me["user"]["id"])


async def spend(session: AsyncSession, user_id: uuid.UUID, tokens: int) -> None:
    """Студент сегодня уже потратил tokens токенов на ключе сервиса."""
    await service.record_usage(session, user_id, uuid.uuid4(), tokens - 1, 1, Decimal("0.01"))
    await session.commit()


async def send(client: AsyncClient, project: Project) -> Any:
    # Any — ответ httpx.
    return await client.post(f"{API}/projects/{project['id']}/messages", json={"text": "Отчёт"})


def next_moscow_midnight(now: datetime) -> datetime:
    """Ближайшая полночь по Москве (UTC+3, без летнего времени) — в UTC."""
    moscow = now.astimezone(UTC) + timedelta(hours=3)
    midnight = datetime(moscow.year, moscow.month, moscow.day, tzinfo=UTC) + timedelta(days=1)
    return midnight - timedelta(hours=3)


async def test_fresh_day_shows_full_quota(user_client: AsyncClient) -> None:
    response = await user_client.get(f"{API}/usage")

    assert response.status_code == 200
    body = response.json()
    resets_at = datetime.fromisoformat(body["resets_at"])
    assert (body["tokens_used"], body["tokens_limit"], body["own_key"]) == (0, LIMIT, False)
    assert resets_at == next_moscow_midnight(datetime.now(UTC))
    assert body["resets_at"].endswith("Z")


async def test_usage_counts_input_and_output_tokens(
    user_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id = await owner(user_client)
    await service.record_usage(db_session, user_id, uuid.uuid4(), 300, 50, Decimal(0))
    await service.record_usage(db_session, user_id, None, 100, 10, Decimal(0))

    body = (await user_client.get(f"{API}/usage")).json()

    assert body["tokens_used"] == 460


async def test_usage_shows_own_key(user_client: AsyncClient, db_session: AsyncSession) -> None:
    await store_key(db_session, await owner(user_client), llm_settings())

    assert (await user_client.get(f"{API}/usage")).json()["own_key"] is True


async def test_usage_is_readable_by_token(user_client: AsyncClient) -> None:
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    response = await user_client.get(f"{API}/usage")

    assert response.status_code == 200
    assert response.json()["tokens_limit"] == LIMIT


async def test_run_is_allowed_until_limit_is_reached(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    enqueued: list[uuid.UUID],
) -> None:
    await spend(db_session, await owner(user_client), LIMIT - 1)

    response = await send(user_client, project)

    assert response.status_code == 201, response.text


async def test_exhausted_quota_blocks_new_run(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    enqueued: list[uuid.UUID],
) -> None:
    await spend(db_session, await owner(user_client), LIMIT)

    response = await send(user_client, project)

    assert response.status_code == 429
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("quota_exceeded", service.QUOTA_MESSAGE)
    usage = (await user_client.get(f"{API}/usage")).json()
    assert error["details"] == {"resets_at": usage["resets_at"]}
    # Ничего не сохранено и в очередь не ушло.
    assert enqueued == []
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AgentRun)) == 0


async def test_own_key_ignores_exhausted_quota(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    enqueued: list[uuid.UUID],
) -> None:
    user_id = await owner(user_client)
    await spend(db_session, user_id, LIMIT * 2)
    await store_key(db_session, user_id, llm_settings())

    response = await send(user_client, project)

    assert response.status_code == 201, response.text


async def test_key_for_previous_provider_does_not_lift_quota(
    app: FastAPI,
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    enqueued: list[uuid.UUID],
) -> None:
    user_id = await owner(user_client)
    await spend(db_session, user_id, LIMIT)
    await store_key(db_session, user_id, llm_settings())
    app.state.settings = llm_settings(
        templates_dir=TEMPLATE_FIXTURES,
        llm_daily_token_limit=LIMIT,
        llm_default_provider="backup",
    )

    response = await send(user_client, project)

    assert response.status_code == 429
    assert (await user_client.get(f"{API}/usage")).json()["own_key"] is False


async def test_running_project_answers_locked_before_quota(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    enqueued: list[uuid.UUID],
) -> None:
    first = await send(user_client, project)
    assert first.status_code == 201
    await spend(db_session, await owner(user_client), LIMIT)

    response = await send(user_client, project)

    # ИИ уже работает с проектом — это важнее лимита: интерфейс покажет «Остановить».
    assert response.status_code == 423


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 11, 11, 9, 0, tzinfo=UTC), datetime(2026, 11, 11, 21, 0, tzinfo=UTC)),
        (
            datetime(2026, 11, 11, 20, 59, 59, tzinfo=UTC),
            datetime(2026, 11, 11, 21, 0, tzinfo=UTC),
        ),
        (datetime(2026, 11, 11, 21, 0, tzinfo=UTC), datetime(2026, 11, 12, 21, 0, tzinfo=UTC)),
        (datetime(2026, 12, 31, 22, 0, tzinfo=UTC), datetime(2027, 1, 1, 21, 0, tzinfo=UTC)),
    ],
    ids=["morning", "last-second", "midnight", "new-year"],
)
async def test_quota_resets_at_next_moscow_midnight(
    db_session: AsyncSession, moment: datetime, expected: datetime
) -> None:
    assert await db_session.scalar(select(service.quota_resets_at(moment))) == expected
