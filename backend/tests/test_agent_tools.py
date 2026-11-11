import asyncio
from uuid import uuid4

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.modules.agent.contract import RunRequest
from app.modules.agent.tools import register_tools
from app.modules.projects.tools import ToolContext
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
