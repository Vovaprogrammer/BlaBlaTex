import asyncio
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.modules.agent.contract import RunRequest
from app.modules.agent.tools import register_tools
from app.modules.checks.schemas import CheckResult
from app.modules.projects.tools import ToolContext, ToolError, ToolErrorCode
from tests.fake_project_tools import FakeProjectTools, build_ok
from tests.fake_run_events import FakeRunEvents


async def test_project_tools_are_bound_and_report_errors() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert {tool.name for tool in info.function_tools} == {
            "list_files",
            "read_file",
            "search",
            "write_file",
            "edit_file",
            "delete_file",
            "compile",
            "run_checks",
            "list_materials",
            "read_material",
            "get_image",
            "get_template_guide",
            "get_profile",
        }
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "edit_file", {"path": "main.tex", "old": "старый", "new": "новый"}, "edit"
                    ),
                    ToolCallPart("compile", {}, "compile"),
                    ToolCallPart("read_file", {"path": "missing.tex"}, "missing"),
                ]
            )
        returned = {
            p.tool_call_id: p.content for p in messages[-1].parts if isinstance(p, ToolReturnPart)
        }
        assert returned["missing"] == events.events[-1].data["summary"]
        return ModelResponse(parts=[TextPart("Отчёт собран.")])

    tools = FakeProjectTools({"main.tex": "старый"}, builds=[build_ok()])
    events = FakeRunEvents()
    request = RunRequest(
        uuid4(), [], ToolContext(uuid4(), uuid4(), "ai", None), tools, events, asyncio.Event(), 1000
    )
    agent = Agent(FunctionModel(model), deps_type=RunRequest)
    register_tools(agent)

    assert (await agent.run("Собери отчёт", deps=request)).output == "Отчёт собран."
    assert (await tools.read_file("main.tex")).text == "1\tновый"
    assert events.types == ["run.tool_call", "run.tool_result"] * 3
    assert [event.data["call_id"] for event in events.events] == [
        "edit",
        "edit",
        "compile",
        "compile",
        "missing",
        "missing",
    ]
    assert [event.data["ok"] for event in events.events[1::2]] == [True, True, False]


@pytest.mark.parametrize("outcome", ["findings", "pending", "error"])
async def test_run_checks_returns_result_and_events(outcome: str) -> None:
    class ChecksTools(FakeProjectTools):
        async def run_checks(self) -> CheckResult:
            if outcome == "error":
                raise ToolError(ToolErrorCode.INTERNAL, "Проверка недоступна.")
            result = await super().run_checks()
            if outcome == "pending":
                result.pdf_checked = False
            return result

    tools = ChecksTools(
        {"main.tex": "\\input{sections/goal.tex}", "sections/goal.tex": "\\section{Цель}\nTODO\n"},
        checks=["placeholder"],
    )
    events = FakeRunEvents()
    request = RunRequest(
        uuid4(), [], ToolContext(uuid4(), uuid4(), "ai", None), tools, events, asyncio.Event(), 1000
    )

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("run_checks", {}, "checks")])
        result = next(p.content for p in messages[-1].parts if isinstance(p, ToolReturnPart))
        if outcome == "error":
            assert result == "Проверка недоступна."
        else:
            assert isinstance(result, CheckResult)
            assert result.pdf_checked is (outcome == "findings")
            assert len(result.findings) == 1
            assert result.findings[0].check == "placeholder"
        return ModelResponse(parts=[TextPart("Проверка завершена.")])

    agent = Agent(FunctionModel(model), deps_type=RunRequest)
    register_tools(agent)
    await agent.run("Проверь отчёт", deps=request)

    assert events.types == ["run.tool_call", "run.tool_result"]
    assert events.events[-1].data["ok"] is (outcome != "error")
