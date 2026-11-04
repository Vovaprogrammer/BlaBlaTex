"""Гонки чата на настоящих отдельных соединениях (architecture.md 8): одновременные
сообщения не начинают второй прогон.

Обычные тесты идут в одной транзакции с откатом, а в одном соединении гонку не увидеть.
"""

import asyncio
import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.chat.dependencies import get_run_enqueue
from app.modules.chat.models import AgentRun
from tests.helpers import TEST_TEMPLATES


async def new_project(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"title": "Гонка", "template_slug": "test-lab", "fields": TEST_TEMPLATES["test-lab"]},
    )
    assert response.status_code == 201, response.text
    project_id: str = response.json()["id"]
    return project_id


async def test_parallel_messages_start_one_run(live_app: FastAPI, live_client: AsyncClient) -> None:
    enqueued: list[uuid.UUID] = []

    async def enqueue(run_id: uuid.UUID) -> None:
        enqueued.append(run_id)

    live_app.dependency_overrides[get_run_enqueue] = lambda: enqueue
    pid = await new_project(live_client)
    url = f"/api/v1/projects/{pid}/messages"
    # Соединения открываются заранее: иначе первый запрос закончится раньше остальных.
    await asyncio.gather(*(live_client.get(url) for _ in range(5)))

    responses = await asyncio.gather(
        *(live_client.post(url, json={"text": f"Вопрос {i}"}) for i in range(5))
    )

    assert sorted(r.status_code for r in responses) == [201, 423, 423, 423, 423]
    [created] = [r.json() for r in responses if r.status_code == 201]
    run_id = created["run"]["id"]
    assert all(
        r.json()["error"]["details"] == {"run_id": run_id}
        for r in responses
        if r.status_code == 423
    )
    assert enqueued == [uuid.UUID(run_id)]
    async with live_app.state.db_sessionmaker() as session:
        runs = await session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.project_id == uuid.UUID(pid))
        )
    assert runs == 1
