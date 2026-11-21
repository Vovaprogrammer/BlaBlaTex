import asyncio
from uuid import uuid4

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.modules.agent.contract import RunRequest
from app.modules.agent.tools import register_tools
from app.modules.builds.schemas import BuildError
from app.modules.projects.tools import BuildResult, ToolContext
from tests.fake_project_tools import FakeProjectTools
from tests.fake_run_events import FakeRunEvents


async def test_compile_returns_at_most_five_errors_without_warnings() -> None:
    errors = [
        BuildError(
            file="main.tex", line=n, message=f"error {n}", context=f"{n}\tline", severity="error"
        )
        for n in range(1, 8)
    ]
    warning = BuildError(file=None, line=None, message="warning", context="", severity="warning")
    build = BuildResult(
        status="error", build_id=uuid4(), pages=None, errors=[warning, *errors], warnings_count=1
    )
    tools = FakeProjectTools({"main.tex": "test"}, builds=[build])
    request = RunRequest(
        uuid4(),
        [],
        ToolContext(uuid4(), uuid4(), "ai", None),
        tools,
        FakeRunEvents(),
        asyncio.Event(),
        1000,
    )

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("compile", {}, "build")])
        result = next(p.content for p in messages[-1].parts if isinstance(p, ToolReturnPart))
        assert isinstance(result, BuildResult)
        assert result.errors == errors[:5]
        assert result.warnings_count == 1
        return ModelResponse(parts=[TextPart("Готово")])

    agent = Agent(FunctionModel(model), deps_type=RunRequest)
    register_tools(agent)
    await agent.run("Собери", deps=request)
    assert build.errors == [warning, *errors]
