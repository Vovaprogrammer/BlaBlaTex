"""Сценарии проверяют управление инструментами на фейке, а не реальную сборку TeX."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from app.modules.agent import runner
from app.modules.agent.contract import HistoryMessage, RunRequest
from app.modules.builds.schemas import BuildError
from app.modules.projects.tools import BuildResult, ToolContext
from tests.fake_project_tools import FakeProjectTools, build_ok
from tests.fake_run_events import FakeRunEvents

FIXTURES = Path(__file__).parent / "fixtures" / "agent_broken_tex"
CASES = [
    ("unclosed_brace", r"\textbf{Текст", r"\textbf{Текст}"),
    ("unknown_command", r"\textbff{Текст}", r"\textbf{Текст}"),
    ("underscore", "file_name", r"file\_name"),
    ("missing_image", r"\includegraphics{missing.png}", ""),
    (
        "unclosed_environment",
        r"\begin{itemize}\item Текст",
        r"\begin{itemize}\item Текст\end{itemize}",
    ),
    ("extra_brace", "Текст}", "Текст"),
    ("missing_math_delimiter", r"\frac{1}{2}", r"$\frac{1}{2}$"),
    ("wrong_environment", r"\end{enumerate}", r"\end{itemize}"),
    ("undefined_reference_command", r"\unknownreference{sec:intro}", r"\ref{sec:intro}"),
    ("unknown_package", r"\usepackage{package_that_does_not_exist}", ""),
]


@pytest.mark.parametrize("name,old,new", CASES)
async def test_scripted_fix_cycle(
    monkeypatch: pytest.MonkeyPatch, name: str, old: str, new: str
) -> None:
    source = (FIXTURES / f"{name}.tex").read_text(encoding="utf-8")
    assert source.count(old) == 1
    line = source[: source.index(old)].count("\n") + 1
    error = BuildError(
        file="main.tex",
        line=line,
        message="Тестовая ошибка",
        context=f"{line}\t{old}",
        severity="error",
    )
    failed = BuildResult(
        status="error", build_id=uuid4(), pages=None, warnings_count=0, errors=[error]
    )
    tools = FakeProjectTools({"main.tex": source}, builds=[failed, build_ok()])
    events = FakeRunEvents()
    request = RunRequest(
        uuid4(),
        [HistoryMessage(role="user", text="Исправь сборку")],
        ToolContext(uuid4(), uuid4(), "ai", None),
        tools,
        events,
        asyncio.Event(),
        5000,
    )

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        step = sum(isinstance(message, ModelResponse) for message in messages)
        if step in (0, 2):
            yield {0: DeltaToolCall("compile", "{}", tool_call_id=f"build-{step}")}
        elif step == 1:
            args = json.dumps({"path": "main.tex", "old": old, "new": new}, ensure_ascii=False)
            yield {0: DeltaToolCall("edit_file", args, tool_call_id="edit")}
        else:
            yield "Готово."

    monkeypatch.setattr(
        runner, "get_model", lambda role, key: FunctionModel(stream_function=stream)
    )
    result = await runner.run_agent(request)
    assert result.status == "done"
    assert (await tools.read_file("main.tex")).text
    assert events.types == ["run.tool_call", "run.tool_result"] * 3 + ["run.delta"]
