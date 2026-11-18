"""Сквозной тест сценарной модели: API, Taskiq job, Postgres, Redis и фейк компилятора."""

import uuid
from functools import partial

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from taskiq import InMemoryBroker

from app.core.events import EventBus
from app.modules.agent import models
from app.modules.agent import runner as agent_runner
from app.modules.builds.service import run_project_builds
from app.modules.chat import runner, tasks
from app.modules.chat.dependencies import get_run_enqueue
from tests.fake_compiler import PDF, FakeCompiler
from tests.helpers import TEST_TEMPLATES


async def test_scripted_run_via_api_and_worker(
    live_app: FastAPI,
    live_client: AsyncClient,
    event_bus: EventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = live_app.state.settings.model_copy(update={"llm_test_mode": "scripted"})
    assert settings.app_env == "test"
    monkeypatch.setattr(models, "get_settings", lambda: settings)
    monkeypatch.setattr(agent_runner, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    def no_provider(*args: object, **kwargs: object) -> None:
        raise AssertionError("Тестовый сценарий не должен подключать провайдера")

    monkeypatch.setattr(models, "_provider_model", no_provider)
    compiler = FakeCompiler()
    sessions = live_app.state.db_sessionmaker
    storage = live_app.state.storage
    enqueued: list[uuid.UUID] = []

    async def enqueue(run_id: uuid.UUID) -> None:
        enqueued.append(run_id)

    async def build(build_id: uuid.UUID) -> None:
        client = compiler.client()
        async with client.http:
            await run_project_builds(sessions, storage, client, event_bus, build_id)

    # Только постановка сборки синхронизируется с тестом; сама работа сборщика настоящая.
    monkeypatch.setattr(
        runner, "ServiceProjectTools", partial(runner.ServiceProjectTools, enqueue=build)
    )
    live_app.dependency_overrides[get_run_enqueue] = lambda: enqueue
    created = await live_client.post(
        "/api/v1/projects",
        json={
            "title": "Тест сценария",
            "template_slug": "test-lab",
            "fields": TEST_TEMPLATES["test-lab"],
        },
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    url = f"/api/v1/projects/{project_id}/messages"
    posted = await live_client.post(url, json={"text": "Сделай отчёт"})
    assert posted.status_code == 201
    [run_id] = enqueued

    broker = InMemoryBroker(await_inplace=True)
    broker.local_task_registry[tasks.run_agent_job.task_name] = tasks.run_agent_job
    broker.state.sessionmaker = sessions
    broker.state.storage = storage
    broker.state.events = event_bus
    broker.state.templates = live_app.state.templates
    broker.state.compiler = compiler.client()
    try:
        await tasks.run_agent_job.kicker().with_broker(broker).kiq(run_id)
    finally:
        await broker.shutdown()

    page = await live_client.get(url)
    assert page.status_code == 200
    assert page.json()["active_run"] is None
    reply = page.json()["items"][-1]
    assert reply["status"] == "done"
    tool_parts = [part for part in reply["parts"] if part["type"] == "tool"]
    assert [part["tool"] for part in tool_parts] == [
        "write_file",
        "edit_file",
        "write_file",
        "compile",
    ]
    assert all(part["ok"] for part in tool_parts)
    assert any(
        part.get("text") == "Тестовый сценарий выполнен, PDF собран." for part in reply["parts"]
    )
    saved = await live_client.get(f"/api/v1/projects/{project_id}/files/sections/scripted-test.tex")
    assert saved.status_code == 200
    assert "Сценарий: готово." in saved.text
    progress = await live_client.get(f"/api/v1/projects/{project_id}/files/sections/progress.tex")
    assert progress.status_code == 200
    assert "\\input{sections/scripted-test}" in progress.text
    [request] = compiler.requests
    assert b"scripted-test" in request.files()["sections/progress.tex"]
    latest = await live_client.get(f"/api/v1/projects/{project_id}/builds/latest?status=ok")
    assert latest.status_code == 200
    pdf = await live_client.get(f"/api/v1/builds/{latest.json()['id']}/pdf")
    assert (pdf.status_code, pdf.content) == (200, PDF)
    events = await event_bus.read(uuid.UUID(project_id), "0-0")
    assert any(event.type == "run.finished" for event in events)
