"""Гонки чата на настоящих отдельных соединениях (architecture.md 8): одновременные
сообщения не начинают второй прогон, а прогон не начинается посреди сохранения.

Обычные тесты идут в одной транзакции с откатом, а в одном соединении гонку не увидеть.
"""

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.errors import AppError
from app.modules.agent.contract import RunRequest, RunResult
from app.modules.chat.dependencies import get_run_enqueue
from app.modules.chat.models import AgentRun
from app.modules.projects import history
from app.modules.projects import service as projects_service
from app.modules.templates.registry import load_templates
from tests.fake_events import FakeEvents
from tests.helpers import TEMPLATE_FIXTURES, TEST_TEMPLATES, writer
from tests.live_builds import Live
from tests.live_runs import USAGE, execute, new_run, stored_run, wait_status


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


async def test_run_waits_for_save_in_progress(live: Live) -> None:
    project_id, run_id = await new_run(live)
    release = asyncio.Event()

    async def agent(request: RunRequest) -> RunResult:
        await release.wait()
        return RunResult(status="done", text="Готово", usage=USAGE)

    templates = load_templates(TEMPLATE_FIXTURES)
    async with live.sessionmaker() as saving:
        # Вкладка начала сохранение: строка проекта заблокирована до его commit.
        assert await history.lock_project(saving, project_id, writer()) is not None
        job = asyncio.create_task(execute(live, run_id, FakeEvents(), templates, agent))
        await asyncio.sleep(0.3)
        # Прогон ждёт: начать посреди сохранения он не может.
        assert not job.done()
        assert (await stored_run(live, run_id)).status == "queued"
        await projects_service.write_text_file(saving, writer(), project_id, "saved.tex", "да")
    try:
        await wait_status(live, run_id, "running")
        # Начатое раньше сохранение прошло, а следующее уже видит блокировку.
        async with live.sessionmaker() as session:
            assert await projects_service.find_file(session, project_id, "saved.tex") is not None
            with pytest.raises(AppError) as locked:
                await projects_service.write_text_file(
                    session, writer(), project_id, "late.tex", "нет"
                )
        assert locked.value.status == 423
    finally:
        release.set()
        await job
    assert (await stored_run(live, run_id)).status == "done"
