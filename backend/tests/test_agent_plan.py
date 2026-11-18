import asyncio

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.modules.agent import planner
from tests.fake_make_plan import plan_request
from tests.fake_project_tools import FakeMaterial, FakeProjectTools


async def test_model_reads_material_and_returns_structured_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert {tool.name for tool in info.function_tools} == {"read_material", "get_image"}
        if not any(isinstance(message, ModelResponse) for message in messages):
            return ModelResponse(
                parts=[ToolCallPart("read_material", {"path": "materials/task.txt"})]
            )
        assert any(
            isinstance(part, ToolReturnPart) and "Требуется вывод" in str(part.content)
            for message in messages
            for part in message.parts
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "sections": [
                            {
                                "section_id": "progress",
                                "materials": ["materials/task.txt"],
                                "note": "Описать решение; не хватает вывода программы.",
                            }
                        ]
                    },
                )
            ]
        )

    tools = FakeProjectTools(
        materials={"materials/task.txt": FakeMaterial(content="x", text="Требуется вывод")}
    )
    request = await plan_request(tools)
    monkeypatch.setattr(planner, "get_model", lambda role, key: FunctionModel(model))
    result = await planner.make_plan(request)
    assert result.status == "done"
    assert result.plan is not None
    assert result.plan.sections[0].materials == ["materials/task.txt"]
    assert "не хватает" in result.plan.sections[0].note
    assert result.usage.tokens_in > 0
    assert tools.calls == ["read_material"]


async def test_cancellation_interrupts_waiting_model(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = asyncio.Event()

    async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    request = await plan_request(FakeProjectTools())
    monkeypatch.setattr(planner, "get_model", lambda role, key: FunctionModel(model))
    async with asyncio.timeout(2):
        task = asyncio.create_task(planner.make_plan(request))
        await entered.wait()
        request.cancel.set()
        result = await task
    assert result.status == "cancelled"
    assert result.plan is None


async def test_material_error_is_returned_to_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not any(isinstance(message, ModelResponse) for message in messages):
            return ModelResponse(
                parts=[ToolCallPart("read_material", {"path": "materials/missing.txt"})]
            )
        assert any(
            isinstance(part, ToolReturnPart) and "не найден" in str(part.content).lower()
            for message in messages
            for part in message.parts
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"sections": []})])

    monkeypatch.setattr(planner, "get_model", lambda role, key: FunctionModel(model))
    result = await planner.make_plan(await plan_request(FakeProjectTools()))
    assert result.status == "done"


async def test_cancellation_wins_race_with_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    request = await plan_request(FakeProjectTools())

    async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request.cancel.set()
        raise ModelHTTPError(status_code=503, model_name="test")

    monkeypatch.setattr(planner, "get_model", lambda role, key: FunctionModel(model))
    result = await planner.make_plan(request)
    assert result.status == "cancelled"
    assert result.error is None


async def test_failed_run_keeps_model_responses_for_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart("read_material", {"path": "materials/a.txt"})])
        raise ModelHTTPError(status_code=503, model_name="test")

    original_usage = planner._usage
    captured: list[ModelMessage] = []

    def record_usage(usage, messages, model_name):
        captured.extend(messages)
        return original_usage(usage, messages, model_name)

    monkeypatch.setattr(planner, "get_model", lambda role, key: FunctionModel(model))
    monkeypatch.setattr(planner, "_usage", record_usage)
    result = await planner.make_plan(await plan_request(FakeProjectTools()))
    assert result.status == "failed"
    assert result.usage.tokens_in > 0
    assert any(isinstance(message, ModelResponse) for message in captured)


@pytest.mark.parametrize("mode", ["unavailable", "limit", "cancelled", "configuration"])
async def test_failure_statuses(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if mode == "unavailable":
            raise ModelHTTPError(status_code=503, model_name="test")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"sections": []})])

    def get_model(role: str, key: object) -> FunctionModel:
        if mode == "configuration":
            raise ValueError("configuration")
        return FunctionModel(model)

    monkeypatch.setattr(planner, "get_model", get_model)
    request = await plan_request(FakeProjectTools(), max_tokens=1 if mode == "limit" else 10000)
    if mode == "cancelled":
        request.cancel.set()
    result = await planner.make_plan(request)
    assert result.status == ("cancelled" if mode == "cancelled" else "failed")
    assert result.plan is None
    if mode == "limit":
        assert result.error == planner.LIMIT_ERROR
    if mode == "unavailable":
        assert result.error == planner.MODEL_ERROR
