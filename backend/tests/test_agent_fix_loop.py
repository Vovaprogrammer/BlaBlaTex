import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from app.modules.agent import runner
from app.modules.agent.contract import HistoryMessage, RunRequest
from app.modules.agent.fix_loop import FixLoop, FixLoopStopped
from app.modules.builds.schemas import BuildError
from app.modules.projects.tools import BuildResult, ToolContext
from tests.fake_project_tools import FakeProjectTools, build_ok
from tests.fake_run_events import FakeRunEvents


def failed(message: str = "Ошибка", line: int | None = 4) -> BuildResult:
    return BuildResult(
        status="error",
        build_id=uuid4(),
        pages=None,
        warnings_count=0,
        errors=[
            BuildError(
                file="main.tex", line=line, message=message, context="4\tстрока", severity="error"
            )
        ],
    )


def test_repeated_error_stops_and_success_resets() -> None:
    policy = FixLoop()
    policy.check(failed())
    policy.check(build_ok())
    policy.check(failed())
    with pytest.raises(FixLoopStopped, match=r"main\.tex, строка 4: Ошибка"):
        policy.check(failed())


def test_four_different_failures_stop_even_without_diagnostics() -> None:
    policy = FixLoop()
    for number in range(3):
        policy.check(failed(str(number)))
    with pytest.raises(FixLoopStopped, match="предел попыток"):
        policy.check(
            BuildResult(status="timeout", build_id=uuid4(), pages=None, warnings_count=0, errors=[])
        )


async def test_run_stops_on_repeated_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        nonlocal calls
        calls += 1
        yield {0: DeltaToolCall("compile", "{}", tool_call_id=str(calls))}

    events = FakeRunEvents()
    request = RunRequest(
        uuid4(),
        [HistoryMessage(role="user", text="Собери")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        FakeProjectTools({"main.tex": "ошибка"}, builds=[failed()]),
        events,
        asyncio.Event(),
        5000,
    )
    monkeypatch.setattr(
        runner, "get_model", lambda role, key: FunctionModel(stream_function=stream)
    )
    result = await runner.run_agent(request)
    assert result.status == "failed"
    assert result.error and "main.tex, строка 4: Ошибка" in result.error
    assert calls == 2
    assert events.types == ["run.tool_call", "run.tool_result"] * 2
    assert [event.data["ok"] for event in events.events[1::2]] == [False, False]
    assert "повторилась" in events.events[-1].data["summary"]


def test_partial_progress_does_not_stop_loop() -> None:
    policy = FixLoop()
    first = failed("A")
    first.errors += failed("B").errors
    policy.check(first)
    policy.check(failed("B"))
    with pytest.raises(FixLoopStopped, match="повторилась"):
        policy.check(failed("B"))


def test_timeouts_do_not_count_as_repeated_latex_errors() -> None:
    policy = FixLoop()
    timeout = BuildResult(
        status="timeout",
        build_id=uuid4(),
        pages=None,
        warnings_count=0,
        errors=[
            BuildError(
                file=None,
                line=None,
                message="Время ожидания сборки истекло",
                context="",
                severity="error",
            )
        ],
    )
    policy.check(timeout)
    policy.check(timeout)
    policy.check(timeout)
    with pytest.raises(FixLoopStopped, match="Время ожидания сборки истекло") as exc:
        policy.check(timeout)
    assert "повторилась" not in str(exc.value)
    assert "Не удалось дождаться результата сборки" in str(exc.value)
    assert "Не удалось собрать отчёт" not in str(exc.value)
