"""Прогон ждёт, пока разберутся материалы проекта (architecture.md 8): «Сделай отчёт» сразу
после загрузки видит их текст. На настоящих соединениях, как остальные тесты прогонов."""

import asyncio
import dataclasses
import time
import uuid

import pytest

from app.core.events import EventType
from app.modules.agent.contract import RunRequest, RunResult
from app.modules.chat import runner
from app.modules.materials.tasks import extract_material
from app.modules.projects import service as projects_service
from app.modules.templates.registry import Registry, load_templates
from tests.fake_events import FakeEvents
from tests.helpers import TEMPLATE_FIXTURES, writer
from tests.live_builds import Live, new_project
from tests.live_runs import FAST, USAGE, execute, new_run, request_cancel, stored_run, wait_status

# Срок ожидания короче, чем у воркера: тесты не ждут полторы минуты.
WAITING = dataclasses.replace(FAST, materials_wait_s=5, materials_poll_s=0.01)


@pytest.fixture
def templates() -> Registry:
    return load_templates(TEMPLATE_FIXTURES)


async def add_material(live: Live, project_id: uuid.UUID) -> uuid.UUID:
    """Студент положил задание в materials/: текст ещё не извлечён (pending)."""
    async with live.sessionmaker() as session:
        file, _ = await projects_service.write_text_file(
            session, writer(), project_id, "materials/task.md", "Вариант 7"
        )
        return file.id


async def extracted(live: Live, file_id: uuid.UUID) -> None:
    """Воркер разобрал материал."""
    await extract_material(
        file_id, sessionmaker=live.sessionmaker, storage=live.storage, events=FakeEvents()
    )


async def test_agent_starts_after_materials_are_ready(live: Live, templates: Registry) -> None:
    project_id = await new_project(live)
    task = await add_material(live, project_id)
    _, run_id = await new_run(live, project_id=project_id)
    read: list[str] = []

    async def agent(request: RunRequest) -> RunResult:
        material = await request.tools.read_material("materials/task.md")
        read.append(material.text)
        return RunResult(status="done", text="Готово", usage=USAGE)

    job = asyncio.create_task(execute(live, run_id, FakeEvents(), templates, agent, WAITING))
    await wait_status(live, run_id, "running")
    await asyncio.sleep(0.05)
    # Пока задание не разобрано, агент не начинает: иначе он не прочитал бы его.
    assert read == []
    await extracted(live, task)
    async with asyncio.timeout(5):
        await job

    assert read == ["Вариант 7"]
    assert (await stored_run(live, run_id)).status == "done"


async def test_agent_starts_anyway_when_materials_take_too_long(
    live: Live, templates: Registry
) -> None:
    project_id = await new_project(live)
    await add_material(live, project_id)
    _, run_id = await new_run(live, project_id=project_id)
    seen: list[str] = []

    async def agent(request: RunRequest) -> RunResult:
        seen.extend(material.status for material in await request.tools.list_materials())
        return RunResult(status="done", text="", usage=USAGE)

    began = time.monotonic()
    await execute(
        live,
        run_id,
        FakeEvents(),
        templates,
        agent,
        dataclasses.replace(WAITING, materials_wait_s=0.2),
    )

    # Срок вышел — агент работает с тем, что готово, а про остальное скажет студенту сам.
    assert seen == ["pending"]
    assert time.monotonic() - began >= 0.2
    assert (await stored_run(live, run_id)).status == "done"


async def test_cancel_while_waiting_for_materials_skips_agent(
    live: Live, templates: Registry
) -> None:
    project_id = await new_project(live)
    await add_material(live, project_id)
    _, run_id = await new_run(live, project_id=project_id)
    events = FakeEvents()
    called: list[RunRequest] = []

    async def agent(request: RunRequest) -> RunResult:
        called.append(request)
        return RunResult(status="done", text="", usage=USAGE)

    job = asyncio.create_task(execute(live, run_id, events, templates, agent, WAITING))
    await wait_status(live, run_id, "running")
    await request_cancel(live, run_id)
    async with asyncio.timeout(5):
        await job

    run = await stored_run(live, run_id)
    assert (run.status, run.error, run.model) == ("cancelled", None, None)
    assert called == []
    assert events.types[-2:] == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]


async def test_project_without_materials_starts_agent_at_once(
    live: Live, templates: Registry
) -> None:
    _, run_id = await new_run(live)

    began = time.monotonic()
    # Настоящие сроки воркера: ждать нечего, полторы минуты ожидания не тратятся.
    await execute(live, run_id, FakeEvents(), templates, timing=runner.DEFAULT_TIMING)

    assert time.monotonic() - began < 5
    assert (await stored_run(live, run_id)).status == "done"
