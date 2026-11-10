import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import structlog
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from app.modules.agent import runner
from app.modules.agent.contract import HistoryMessage, RunRequest
from app.modules.projects.tools import ToolContext
from tests.fake_project_tools import FakeProjectTools, build_ok
from tests.fake_run_events import FakeRunEvents


@pytest.mark.parametrize(
    "cancel_after,max_tokens,status",
    [
        (None, 5000, "done"),
        (5, 5000, "cancelled"),
        (None, 1, "failed"),
    ],
)
async def test_streamed_run(
    monkeypatch: pytest.MonkeyPatch, cancel_after: int | None, max_tokens: int, status: str
) -> None:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        assert info.function_tools
        assert info.instructions and "`sections/goal.tex`" in info.instructions
        assert isinstance(messages[1], ModelResponse)
        assert messages[1].parts == [TextPart("Уточните задачу.")]
        if len(messages) == 3:
            yield {
                0: DeltaToolCall(
                    "edit_file", '{"path":"main.tex","old":"old","new":"new"}', tool_call_id="edit"
                ),
                1: DeltaToolCall("compile", "{}", tool_call_id="build"),
            }
        else:
            yield "Отчёт "
            yield "собран."

    tools = FakeProjectTools({"main.tex": "old"}, builds=[build_ok()])
    cancel = asyncio.Event()
    events = FakeRunEvents(cancel, cancel_after=cancel_after)
    history = [
        HistoryMessage(role="user", text="Здравствуйте"),
        HistoryMessage(role="assistant", text="Уточните задачу."),
        HistoryMessage(role="user", text="Соберите отчёт"),
    ]
    request = RunRequest(
        history, ToolContext(uuid4(), uuid4(), "ai", None), tools, events, cancel, max_tokens
    )
    monkeypatch.setattr(
        runner, "get_model", lambda role, key: FunctionModel(stream_function=stream)
    )

    result = await runner.run_agent(request)

    assert result.status == status
    assert result.usage.tokens_in > 0
    assert result.text == events.text
    if status == "failed":
        assert result.error == runner.LIMIT_ERROR
        assert (await tools.read_file("main.tex")).text == "1\told"
        assert events.types == []
    else:
        assert result.usage.tokens_out > 0
        assert (await tools.read_file("main.tex")).text == "1\tnew"
        assert events.types[:4] == ["run.tool_call", "run.tool_result"] * 2
        assert result.text == ("Отчёт " if cancel_after else "Отчёт собран.")


async def test_cancel_interrupts_model_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = asyncio.Event()
    entered = asyncio.Event()

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        entered.set()
        await asyncio.Event().wait()
        yield "Опоздавший ответ"

    request = RunRequest(
        [HistoryMessage(role="user", text="Соберите отчёт")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        FakeProjectTools(),
        FakeRunEvents(),
        cancel,
        5000,
    )
    monkeypatch.setattr(
        runner, "get_model", lambda role, key: FunctionModel(stream_function=stream)
    )
    async with asyncio.timeout(2):
        task = asyncio.create_task(runner.run_agent(request))
        await entered.wait()
        cancel.set()
        assert (await task).status == "cancelled"


async def test_run_survives_sloppy_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    # Так вела себя живая модель на B2.9: list_files с {"path": "."}, потом мусорные
    # аргументы. С одним повтором PydanticAI весь прогон падал с MODEL_ERROR.
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        step = sum(isinstance(message, ModelResponse) for message in messages)
        if step == 0:
            yield {0: DeltaToolCall("list_files", '{"path":"."}', tool_call_id="list")}
        elif step in (1, 2):
            yield {0: DeltaToolCall("read_file", '{"file":"main.tex"}', tool_call_id=f"bad{step}")}
        elif step == 3:
            yield {0: DeltaToolCall("read_file", '{"path":"main.tex"}', tool_call_id="read")}
        else:
            yield "Готово."

    events = FakeRunEvents()
    request = RunRequest(
        [HistoryMessage(role="user", text="Соберите отчёт")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        FakeProjectTools({"main.tex": "текст"}),
        events,
        asyncio.Event(),
        50_000,
    )
    monkeypatch.setattr(
        runner, "get_model", lambda role, key: FunctionModel(stream_function=stream)
    )

    result = await runner.run_agent(request)

    assert (result.status, result.text, result.error) == ("done", "Готово.", None)
    tool_events = [event for event in events.events if event.type.startswith("run.tool_")]
    assert [event.data["call_id"] for event in tool_events] == ["list", "list", "read", "read"]
    assert all(event.data["ok"] for event in tool_events[1::2])


async def test_model_failure_returns_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield "Начало "
        raise ModelHTTPError(500, "test", body={"error": "чувствительные данные"})

    request = RunRequest(
        [HistoryMessage(role="user", text="Соберите отчёт")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        FakeProjectTools(),
        FakeRunEvents(),
        asyncio.Event(),
        5000,
    )
    monkeypatch.setattr(
        runner, "get_model", lambda role, key: FunctionModel(stream_function=stream)
    )
    with structlog.testing.capture_logs() as logs:
        result = await runner.run_agent(request)
    assert (result.status, result.text, result.error) == ("failed", "Начало ", runner.MODEL_ERROR)
    # Причина — в логе воркера, тело ответа провайдера — нет.
    failed = [log for log in logs if log["event"] == "agent_model_failed"]
    assert [log["errors"] for log in failed] == [["ModelHTTPError 500 test"]]
    assert "чувствительные данные" not in repr(logs)


def test_usage_prices_each_response_at_its_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    from pydantic_ai.usage import RequestUsage, RunUsage

    from app.core.config import LLMModelSettings, LLMProviderSettings, Settings

    providers = {
        name: LLMProviderSettings(
            base_url=f"https://{name}.example.invalid/v1",
            models={
                role: LLMModelSettings(name="same-model", input_price=price, output_price=price)
                for role in ("main", "fast", "vision")
            },
        )
        for name, price in (("primary", 1), ("backup", 5))
    }
    settings = Settings(
        _env_file=None,
        llm_providers=providers,
        llm_default_provider="primary",
        llm_fallback_provider="backup",
    )
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    messages = [
        ModelResponse(
            parts=[TextPart("Ответ")],
            model_name="same-model",
            provider_url=f"https://{name}.example.invalid/v1/",
            usage=RequestUsage(input_tokens=100, output_tokens=10),
        )
        for name in providers
    ]

    usage = runner._usage(RunUsage(input_tokens=200, output_tokens=20), messages, "default")

    assert (usage.model, usage.tokens_in, usage.tokens_out, usage.cost) == (
        "same-model",
        200,
        20,
        Decimal("0.00066"),
    )
