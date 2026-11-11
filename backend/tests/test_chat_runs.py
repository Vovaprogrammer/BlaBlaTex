"""Прогон агента в воркере (architecture.md 8, 9.3, 9.4): весь цикл «сообщение → прогон →
ответ → события» с заглушкой и с фейковыми агентами, части ответа, история для агента.

Прогон открывает свои сессии и ходит в базу параллельно с агентом, поэтому тесты — на
настоящих соединениях (фикстура live), а не в одной транзакции с откатом.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from functools import partial
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.models.test import TestModel as PydanticTestModel
from sqlalchemy import select
from taskiq import InMemoryBroker

from app.core.events import EventBus, EventType, RunDeltaData, RunFinishedData
from app.modules.agent import runner as agent_runner
from app.modules.agent import stub
from app.modules.agent.contract import HistoryMessage, ModelUsage, RunRequest, RunResult
from app.modules.builds.service import run_project_builds
from app.modules.chat import runner, tasks
from app.modules.chat.dependencies import get_run_enqueue
from app.modules.chat.models import AgentRun, ChatMessage
from app.modules.materials.tasks import extract_material
from app.modules.projects.models import Changeset, Project
from app.modules.projects.service import read_file
from app.modules.templates.registry import Registry, load_templates
from tests.fake_compiler import PDF, FakeCompiler
from tests.fake_events import FakeEvents
from tests.helpers import TEMPLATE_FIXTURES, TEST_TEMPLATES
from tests.live_builds import Live, new_project
from tests.live_runs import USAGE, execute, new_run, parts, reply_of, stored_run, usage_of
from tests.llm_settings import STUDENT_KEY, llm_settings, store_key


@pytest.fixture
def templates() -> Registry:
    return load_templates(TEMPLATE_FIXTURES)


def done(text: str = "", usage: ModelUsage = USAGE) -> RunResult:
    return RunResult(status="done", text=text, usage=usage)


async def test_stub_run_answers_and_sends_events(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    events = FakeEvents()

    await execute(live, run_id, events, templates)

    reply = await reply_of(live, project_id)
    assert (reply.status, reply.seq) == ("done", 1)
    assert parts(reply) == [{"type": "text", "text": stub.STUB_REPLY}]
    run = await stored_run(live, run_id)
    assert (run.status, run.model, run.tokens_in, run.error) == ("done", "stub", 0, None)
    assert run.finished_at is not None
    assert events.types == [
        EventType.PROJECT_LOCKED,
        EventType.RUN_STARTED,
        EventType.RUN_DELTA,
        EventType.RUN_FINISHED,
        EventType.PROJECT_UNLOCKED,
    ]
    locked, started, delta, finished, unlocked = (event.data for event in events.published)
    assert locked.model_dump() == unlocked.model_dump() == {"run_id": run_id}
    assert started.model_dump() == {"run_id": run_id, "message_id": reply.id}
    assert delta == RunDeltaData(run_id=run_id, message_id=reply.id, seq=1, text=stub.STUB_REPLY)
    assert isinstance(finished, RunFinishedData)
    assert (finished.status, finished.changeset_id) == ("done", run.changeset_id)
    assert (finished.usage.tokens_in, finished.usage.tokens_out) == (0, 0)


async def test_run_usage_goes_to_owner_daily_usage(live: Live, templates: Registry) -> None:
    async def agent(request: RunRequest) -> RunResult:
        # Своего ключа нет — агент работает на ключе сервиса.
        assert request.user_key is None
        return done("Готово")

    _, first = await new_run(live)
    await execute(live, first, FakeEvents(), templates, agent)
    _, second = await new_run(live)
    await execute(live, second, FakeEvents(), templates, agent)

    assert await usage_of(live) == (240, 90, Decimal("0.0042"), 2)


async def test_run_with_own_key_uses_it_and_spends_no_quota(
    live: Live, templates: Registry
) -> None:
    settings = llm_settings(agent_run_max_tokens=10_000)
    async with live.sessionmaker() as session:
        await store_key(session, live.owner_id, settings)
    keys: list[str | None] = []

    async def agent(request: RunRequest) -> RunResult:
        keys.append(None if request.user_key is None else request.user_key.get_secret_value())
        return done("Готово")

    _, run_id = await new_run(live)
    await execute(live, run_id, FakeEvents(), templates, agent, settings=settings)

    assert keys == [STUDENT_KEY]
    # Расход виден в прогоне, но в учёт и квоту не идёт.
    assert (await stored_run(live, run_id)).tokens_in == USAGE.tokens_in
    assert await usage_of(live) is None


async def test_streamed_text_and_tool_cards_become_parts(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    events = FakeEvents()

    async def agent(request: RunRequest) -> RunResult:
        await request.events.delta("Смотрю ")
        await request.events.delta("")
        await request.events.delta("файлы.")
        await request.events.tool_call("c1", "list_files", "Список файлов")
        files = await request.tools.list_files()
        await request.events.tool_result("c1", True, f"Файлов: {len(files)}")
        await request.events.tool_call("c2", "read_file", "Читаю nope.tex")
        await request.events.tool_result("c2", False, "Нет такого файла")
        await request.events.delta("Готово.")
        # Текст уже пришёл кусками — второй раз он не отправляется.
        return done("Смотрю файлы.Готово.")

    await execute(live, run_id, events, templates, agent)

    reply = await reply_of(live, project_id)
    assert (reply.status, reply.seq) == ("done", 7)
    assert parts(reply) == [
        {"type": "text", "text": "Смотрю файлы."},
        {
            "type": "tool",
            "call_id": "c1",
            "tool": "list_files",
            "summary": "Список файлов",
            "ok": True,
            "result": "Файлов: 1",
        },
        {
            "type": "tool",
            "call_id": "c2",
            "tool": "read_file",
            "summary": "Читаю nope.tex",
            "ok": False,
            "result": "Нет такого файла",
        },
        {"type": "text", "text": "Готово."},
    ]
    run_events = [event.data for event in events.published[2:-2]]
    assert [data.model_dump()["seq"] for data in run_events] == [1, 2, 3, 4, 5, 6, 7]
    run = await stored_run(live, run_id)
    assert (run.model, run.tokens_in, run.tokens_out, run.cost) == (
        "test-model",
        120,
        45,
        Decimal("0.0021"),
    )


async def test_written_files_add_changeset_card(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    events = FakeEvents()

    async def agent(request: RunRequest) -> RunResult:
        await request.tools.write_file("sections/ai.tex", "Текст ИИ\n")
        return done("Добавил раздел.")

    await execute(live, run_id, events, templates, agent)

    run = await stored_run(live, run_id)
    reply = await reply_of(live, project_id)
    assert parts(reply) == [
        {"type": "text", "text": "Добавил раздел."},
        {"type": "changeset", "changeset_id": str(run.changeset_id)},
    ]
    # Правки агента — в changeset прогона, автор — ИИ, события те же, что у правок сайта.
    file_events = [e.data for e in events.published if e.type == EventType.FILE_CHANGED]
    assert [(e.changeset_id, e.author) for e in file_events] == [(run.changeset_id, "ai")]
    async with live.sessionmaker() as session:
        changeset = await session.get(Changeset, run.changeset_id)
        assert changeset is not None
        assert (changeset.author, changeset.run_id) == ("ai", run_id)


async def test_failed_result_shows_error(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    events = FakeEvents()

    async def agent(request: RunRequest) -> RunResult:
        return RunResult(
            status="failed", text="", error="Лимит токенов на запрос исчерпан", usage=USAGE
        )

    await execute(live, run_id, events, templates, agent)

    reply = await reply_of(live, project_id)
    assert reply.status == "failed"
    assert parts(reply) == [{"type": "error", "text": "Лимит токенов на запрос исчерпан"}]
    run = await stored_run(live, run_id)
    assert (run.status, run.error, run.tokens_in) == (
        "failed",
        "Лимит токенов на запрос исчерпан",
        120,
    )
    assert events.types[-2:] == [EventType.RUN_FINISHED, EventType.PROJECT_UNLOCKED]
    assert events.published[-2].data.model_dump()["status"] == "failed"


async def test_agent_crash_fails_with_general_message(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live, "Секретный текст студента")
    events = FakeEvents()

    async def agent(request: RunRequest) -> RunResult:
        await request.events.delta("Начинаю")
        raise RuntimeError("сбой в коде агента")

    with structlog.testing.capture_logs() as logs:
        await execute(live, run_id, events, templates, agent)

    reply = await reply_of(live, project_id)
    assert reply.status == "failed"
    # Текст, который успел прийти, остаётся.
    assert parts(reply) == [
        {"type": "text", "text": "Начинаю"},
        {"type": "error", "text": runner.RUN_FAILED_MESSAGE},
    ]
    run = await stored_run(live, run_id)
    assert (run.status, run.error, run.model) == ("failed", runner.RUN_FAILED_MESSAGE, None)
    assert "agent_run_crashed" in [log["event"] for log in logs]
    # История чата и ответ в логи не попадают.
    assert "Секретный текст студента" not in repr(logs)
    assert "Начинаю" not in repr(logs)


async def test_parts_are_saved_during_run(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    release = asyncio.Event()

    async def agent(request: RunRequest) -> RunResult:
        await request.events.delta("Пишу введение")
        await request.events.tool_call("c1", "compile", "Собираю PDF")
        await release.wait()
        await request.events.tool_result("c1", True, "PDF собран")
        return done()

    job = asyncio.create_task(execute(live, run_id, FakeEvents(), templates, agent))
    try:
        async with asyncio.timeout(5):
            # Ждём запись в базе: о ней воркер не сообщает, остаётся спрашивать.
            while (reply := await reply_of(live, project_id)).seq < 2:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        # Вкладка, открытая посреди прогона, видит то, что уже пришло, и номер события.
        assert reply.status == "running"
        assert parts(reply) == [
            {"type": "text", "text": "Пишу введение"},
            {
                "type": "tool",
                "call_id": "c1",
                "tool": "compile",
                "summary": "Собираю PDF",
                "ok": None,
                "result": None,
            },
        ]
    finally:
        release.set()
        await job

    reply = await reply_of(live, project_id)
    assert (reply.status, reply.seq) == ("done", 3)
    assert parts(reply)[1]["result"] == "PDF собран"


async def test_agent_gets_recent_history_and_request(live: Live, templates: Registry) -> None:
    project_id = await new_project(live)
    async with live.sessionmaker() as session:
        for number in range(30):
            role = "user" if number % 2 == 0 else "assistant"
            text = f"m{number}"
            if number == 27:
                # Ответ, где были только карточки инструментов: текста нет.
                items: list[dict[str, Any]] = [
                    {"type": "tool", "call_id": "c", "tool": "compile", "summary": "PDF"}
                ]
            elif number == 29:
                items = [
                    {"type": "text", "text": "x" * 5000},
                    {"type": "tool", "call_id": "c", "tool": "compile", "summary": "PDF"},
                    {"type": "text", "text": "итог"},
                ]
            else:
                items = [{"type": "text", "text": text}]
            session.add(ChatMessage(project_id=project_id, role=role, parts=items))
        await session.commit()
    request_text = "Запрос " + "я" * 6000
    _, run_id = await new_run(live, request_text, project_id)
    seen: list[HistoryMessage] = []

    async def agent(request: RunRequest) -> RunResult:
        seen.extend(request.history)
        assert request.max_tokens == 10_000
        assert request.user_key is None
        assert request.context.actor == "ai"
        return done("Ок")

    await execute(live, run_id, FakeEvents(), templates, agent)

    # 20 сообщений до запроса (m10…m29) без пустого m27 и сам запрос.
    assert [m.text for m in seen[:-2]] == [f"m{n}" for n in range(10, 27)] + ["m28"]
    assert [m.role for m in seen[:2]] == ["user", "assistant"]
    long_reply = seen[-2]
    assert long_reply.role == "assistant"
    assert long_reply.text == "x" * runner.HISTORY_MESSAGE_MAX_CHARS + "\n" + runner.SHORTENED_MARK
    # Запрос передаётся целиком, каким бы длинным он ни был.
    assert (seen[-1].role, seen[-1].text) == ("user", request_text)


async def test_redelivered_job_does_nothing(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    calls: list[uuid.UUID] = []

    async def agent(request: RunRequest) -> RunResult:
        calls.append(request.context.project_id)
        return done("Ответ")

    first, second = FakeEvents(), FakeEvents()
    await execute(live, run_id, first, templates, agent)
    await execute(live, run_id, second, templates, agent)

    assert calls == [project_id]
    assert second.published == []
    assert (await reply_of(live, project_id)).seq == 1


async def test_run_of_deleted_project_is_skipped(live: Live, templates: Registry) -> None:
    project_id, run_id = await new_run(live)
    async with live.sessionmaker() as session:
        project = await session.get(Project, project_id)
        await session.delete(project)
        await session.commit()
    events = FakeEvents()

    await execute(live, run_id, events, templates)

    assert events.published == []


async def test_job_runs_through_taskiq(
    live: Live, templates: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        agent_runner,
        "get_model",
        lambda role, key: PydanticTestModel(call_tools=[], custom_output_text="Готово."),
    )
    # Задача получает id из очереди, а базу, хранилище, журнал и шаблоны — из ресурсов
    # воркера, как в app/worker.py.
    memory = InMemoryBroker(await_inplace=True)
    memory.local_task_registry[tasks.run_agent_job.task_name] = tasks.run_agent_job
    events = FakeEvents()
    memory.state.sessionmaker = live.sessionmaker
    memory.state.storage = live.storage
    memory.state.events = events
    memory.state.templates = templates
    project_id, run_id = await new_run(live)
    try:
        await tasks.run_agent_job.kicker().with_broker(memory).kiq(run_id)
    finally:
        await memory.shutdown()

    assert (await stored_run(live, run_id)).status == "done"
    assert parts(await reply_of(live, project_id)) == [{"type": "text", "text": "Готово."}]


@pytest.mark.parametrize("with_prompts", [False, True], ids=["baseline", "prompts-v1"])
async def test_full_cycle_through_api_and_redis(
    live_app: FastAPI,
    live_client: AsyncClient,
    event_bus: EventBus,
    monkeypatch: pytest.MonkeyPatch,
    with_prompts: bool,
) -> None:
    enqueued: list[uuid.UUID] = []
    goal = "Проверить сортировку массива."
    section = "sections/goal.tex"
    placeholder = "% Цель — из методички."
    compiler = FakeCompiler()
    sessions = live_app.state.db_sessionmaker
    storage = live_app.state.storage

    async def enqueue(run_id: uuid.UUID) -> None:
        enqueued.append(run_id)

    async def build(build_id: uuid.UUID) -> None:
        client = compiler.client()
        async with client.http:
            await run_project_builds(sessions, storage, client, event_bus, build_id)

    async def model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        if with_prompts:
            assert info.instructions and section in info.instructions
            assert "только из материалов проекта" in info.instructions
        else:
            assert not info.instructions
        if len(messages) == 1:
            yield {0: DeltaToolCall("read_material", '{"path":"materials/task.txt"}')}
        elif len(messages) == 3:
            [returned] = messages[-1].parts
            assert isinstance(returned, ToolReturnPart)
            assert goal in returned.model_response_str()
            args = json.dumps({"path": section, "old": placeholder, "new": goal})
            yield {0: DeltaToolCall("edit_file", args), 1: DeltaToolCall("compile", "{}")}
        else:
            [_, result] = messages[-1].parts
            assert isinstance(result, ToolReturnPart)
            assert json.loads(result.model_response_str())["status"] == "ok"
            yield "Цель добавлена, PDF собран."

    if not with_prompts:
        monkeypatch.setattr(agent_runner, "render_instructions", lambda guide: "")
    monkeypatch.setattr(
        agent_runner, "get_model", lambda role, key: FunctionModel(stream_function=model)
    )
    monkeypatch.setattr(
        runner, "ServiceProjectTools", partial(runner.ServiceProjectTools, enqueue=build)
    )
    live_app.dependency_overrides[get_run_enqueue] = lambda: enqueue
    response = await live_client.post(
        "/api/v1/projects",
        json={"title": "Цикл", "template_slug": "test-lab", "fields": TEST_TEMPLATES["test-lab"]},
    )
    pid = response.json()["id"]
    uploaded = await live_client.post(
        f"/api/v1/projects/{pid}/upload",
        data={"dir": "materials"},
        files={"files": ("task.txt", goal.encode(), "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    async with sessions() as session:
        material = await read_file(session, uuid.UUID(pid), "materials/task.txt")
    await extract_material(
        material.id,
        sessionmaker=sessions,
        storage=storage,
        events=FakeEvents(),
        settings=live_app.state.settings,
    )

    url = f"/api/v1/projects/{pid}/messages"
    posted = (await live_client.post(url, json={"text": "Сделай отчёт"})).json()
    [run_id] = enqueued

    # Воркер: события — в настоящий журнал Redis, откуда их читает SSE.
    await runner.execute_run(
        run_id,
        sessionmaker=live_app.state.db_sessionmaker,
        storage=live_app.state.storage,
        events=event_bus,
        templates=live_app.state.templates,
        run_agent=tasks.AGENT,
        settings=live_app.state.settings,
    )

    page = (await live_client.get(url)).json()
    assert page["active_run"] is None
    user, reply = page["items"]
    assert user == posted["message"]
    assert (reply["id"], reply["status"], reply["seq"]) == (
        posted["run"]["message_id"],
        "done",
        7,
    )
    assert [part["type"] for part in reply["parts"]] == ["tool"] * 3 + ["text", "changeset"]
    assert [part["tool"] for part in reply["parts"][:3]] == [
        "read_material",
        "edit_file",
        "compile",
    ]
    assert all(part["ok"] for part in reply["parts"][:3])
    assert reply["parts"][3]["text"] == "Цель добавлена, PDF собран."
    stored = await event_bus.read(uuid.UUID(pid), "0-0")
    assert [event.type for event in stored if not event.type.startswith(("file.", "build."))] == [
        "project.locked",
        "run.started",
        *(["run.tool_call", "run.tool_result"] * 3),
        "run.delta",
        "run.finished",
        "project.unlocked",
    ]
    async with live_app.state.db_sessionmaker() as session:
        status = await session.scalar(select(AgentRun.status).where(AgentRun.id == run_id))
    assert status == "done"
    [compiled] = compiler.requests
    assert goal in compiled.files()[section].decode()
    latest = await live_client.get(f"/api/v1/projects/{pid}/builds/latest?status=ok")
    pdf = await live_client.get(f"/api/v1/builds/{latest.json()['id']}/pdf")
    assert (pdf.status_code, pdf.content) == (200, PDF)

    changeset_id = reply["parts"][-1]["changeset_id"]
    assert (await live_client.post(f"/api/v1/changesets/{changeset_id}/revert")).status_code == 201
    restored = await live_client.get(f"/api/v1/projects/{pid}/files/{section}")
    assert placeholder in restored.text and goal not in restored.text
