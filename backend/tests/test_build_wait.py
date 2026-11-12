"""GET /builds/{bid}?wait — итог сборки одним запросом (architecture.md 9.1, «Сборки»).

Агент по токену ставит сборку и ждёт итог на сервере, а не опрашивает её каждую секунду.
Ожидание на настоящем пуле соединений — на live_app: там сборку можно закончить из другой
сессии, пока запрос ждёт.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.core.config import Settings
from app.main import create_app
from app.modules.auth.models import User
from app.modules.builds.dependencies import get_enqueue
from app.modules.builds.models import Build
from tests.build_worker import BuildWorker
from tests.fake_events import FakeEvents
from tests.fake_rate_limiter import FakeRateLimiter
from tests.helpers import CSRF, PASSWORD, TEST_TEMPLATES

Json = dict[str, Any]


async def start(client: AsyncClient, pid: str) -> Json:
    response = await client.post(f"/api/v1/projects/{pid}/builds", headers=CSRF)
    assert response.status_code == 202, response.text
    result: Json = response.json()
    return result


async def wait_for(client: AsyncClient, build_id: str, wait: int) -> tuple[Json, float]:
    """Ответ GET /builds/{bid}?wait и сколько секунд он шёл."""
    began = time.monotonic()
    response = await client.get(f"/api/v1/builds/{build_id}", params={"wait": wait})
    assert response.status_code == 200, response.text
    return response.json(), time.monotonic() - began


# Без настоящего пула: данные теста в одной транзакции.


async def test_finished_build_answers_at_once(
    user_client: AsyncClient, build_worker: BuildWorker, project: Json
) -> None:
    queued = await start(user_client, project["id"])
    await build_worker.run()

    build, took = await wait_for(user_client, queued["id"], wait=60)

    assert build["status"] == "ok"
    assert took < 1


async def test_wait_ends_with_build_as_is(
    user_client: AsyncClient, build_worker: BuildWorker, project: Json
) -> None:
    queued = await start(user_client, project["id"])

    build, took = await wait_for(user_client, queued["id"], wait=1)

    # Не дождались: сборка как есть, клиент повторит запрос.
    assert build == queued
    assert took >= 1


@pytest.mark.parametrize("wait", [-1, 61, "abc"])
async def test_wait_out_of_range_is_validation_error(
    user_client: AsyncClient, build_worker: BuildWorker, project: Json, wait: int | str
) -> None:
    queued = await start(user_client, project["id"])

    response = await user_client.get(f"/api/v1/builds/{queued['id']}", params={"wait": wait})

    assert response.status_code == 422
    [error] = response.json()["error"]["details"]["errors"]
    assert error["loc"] == ["query", "wait"]


# На настоящем пуле соединений.


async def _no_queue(build_id: uuid.UUID) -> None:
    """Сборку никто не собирает: тест сам ставит ей итог."""


@pytest.fixture
async def pool_app(db_settings: Settings, tmp_path: Path) -> AsyncIterator[FastAPI]:
    """Приложение с пулом из одного соединения: занятое ожиданием соединение сразу видно —
    другой запрос не дождался бы его."""
    settings = db_settings.model_copy(
        update={"storage_dir": tmp_path / "storage", "db_pool_size": 1, "db_max_overflow": 0}
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.events = FakeEvents()
        app.state.rate_limiter = FakeRateLimiter()
        app.dependency_overrides[get_enqueue] = lambda: _no_queue
        yield app


@pytest.fixture
async def pool_client(pool_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Студент с проектом; после теста пользователь удаляется вместе с проектом."""
    email = f"wait-{uuid.uuid4().hex[:8]}@example.com"
    transport = ASGITransport(app=pool_app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=CSRF) as client:
        response = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD, "consent": True}
        )
        assert response.status_code == 201, response.text
        try:
            yield client
        finally:
            async with pool_app.state.db_sessionmaker() as session:
                await session.execute(delete(User).where(User.email == email))
                await session.commit()


async def new_project(client: AsyncClient) -> str:
    body = {"title": "ЛР 1", "template_slug": "test-lab", "fields": TEST_TEMPLATES["test-lab"]}
    response = await client.post("/api/v1/projects", json=body)
    assert response.status_code == 201, response.text
    pid: str = response.json()["id"]
    return pid


async def finish(app: FastAPI, build_id: str, after_s: float) -> None:
    """Через after_s секунд сборка заканчивается — как у воркера, из другой сессии."""
    await asyncio.sleep(after_s)
    async with app.state.db_sessionmaker() as session:
        await session.execute(
            update(Build).where(Build.id == uuid.UUID(build_id)).values(status="ok", pages=3)
        )
        await session.commit()


async def test_answer_comes_when_build_finishes(
    pool_app: FastAPI, pool_client: AsyncClient
) -> None:
    queued = await start(pool_client, await new_project(pool_client))

    (build, took), _ = await asyncio.gather(
        wait_for(pool_client, queued["id"], wait=30), finish(pool_app, queued["id"], after_s=0.3)
    )

    assert (build["status"], build["pages"]) == ("ok", 3)
    # Статус проверяется раз в секунду: ответ — через секунду-две, а не через 30 с.
    assert took < 3


async def test_waiting_request_does_not_hold_connection(
    pool_app: FastAPI, pool_client: AsyncClient
) -> None:
    pid = await new_project(pool_client)
    queued = await start(pool_client, pid)
    waiting = asyncio.create_task(wait_for(pool_client, queued["id"], wait=30))
    await asyncio.sleep(0.3)

    # Соединение в пуле одно: если бы его держало ожидание, этот запрос встал бы.
    response = await asyncio.wait_for(pool_client.get(f"/api/v1/projects/{pid}/tree"), 5)

    assert response.status_code == 200
    assert not waiting.done()
    await finish(pool_app, queued["id"], after_s=0)
    build, _ = await waiting
    assert build["status"] == "ok"


async def test_shutdown_answers_at_once(pool_app: FastAPI, pool_client: AsyncClient) -> None:
    queued = await start(pool_client, await new_project(pool_client))
    waiting = asyncio.create_task(wait_for(pool_client, queued["id"], wait=30))
    await asyncio.sleep(0.3)

    pool_app.state.shutdown.set()
    build, took = await asyncio.wait_for(waiting, 5)

    # Сервер останавливается: ответ сразу, со сборкой как есть.
    assert build["status"] == "queued"
    assert took < 2


async def test_build_of_deleted_project_is_not_found(pool_client: AsyncClient) -> None:
    pid = await new_project(pool_client)
    queued = await start(pool_client, pid)

    async def delete_project() -> None:
        await asyncio.sleep(0.3)
        response = await pool_client.delete(f"/api/v1/projects/{pid}")
        assert response.status_code == 204, response.text

    response, _ = await asyncio.gather(
        pool_client.get(f"/api/v1/builds/{queued['id']}", params={"wait": 30}), delete_project()
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
