"""Детерминированный сценарий агента для изолированного e2e, без сети."""

import json
from collections.abc import AsyncIterator

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

STEPS: tuple[tuple[str, str, dict[str, str]], ...] = (
    (
        "scripted-create",
        "write_file",
        {"path": "sections/scripted-test.tex", "content": "Сценарий: черновик.\n"},
    ),
    (
        "scripted-edit",
        "edit_file",
        {"path": "sections/scripted-test.tex", "old": "черновик", "new": "готово"},
    ),
    (
        "scripted-include",
        "write_file",
        {
            "path": "sections/progress.tex",
            "content": "\\section{Ход работы}\n\\input{sections/scripted-test}\n",
        },
    ),
    ("scripted-compile", "compile", {}),
)


def _next(messages: list[ModelMessage]) -> tuple[str, str, dict[str, str]] | str:
    # История между сообщениями содержит текст; действия считаем только после последнего запроса.
    start = 0
    for index, message in enumerate(messages):
        if isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart) for part in message.parts
        ):
            start = index
    returns: dict[str, ToolReturnPart] = {}
    for message in messages[start:]:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    returns[part.tool_call_id] = part
    for call_id, name, args in STEPS:
        result = returns.get(call_id)
        if result is None:
            return call_id, name, args
        content = result.model_response_object()
        if result.outcome != "success" or "return_value" in content or "error" in content:
            return "Тестовый сценарий остановлен: инструмент вернул ошибку."
        if name == "compile" and content.get("status") != "ok":
            return "Тестовый сценарий выполнен, но PDF не собрался."
    return "Тестовый сценарий выполнен, PDF собран."


def _response(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if info.output_tools and {tool.name for tool in info.function_tools} == {
        "read_material",
        "get_image",
    }:
        prompt = next(
            part.content
            for message in reversed(messages)
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        _, _, data = prompt.partition("\n\nШаблон и материалы проекта:\n")
        sections = json.loads(data)["guide"]["sections"]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "sections": [
                            {"section_id": section["id"], "materials": [], "note": ""}
                            for section in sections
                        ]
                    },
                )
            ]
        )
    step = _next(messages)
    if isinstance(step, str):
        return ModelResponse(parts=[TextPart(step)])
    call_id, name, args = step
    return ModelResponse(parts=[ToolCallPart(name, args, tool_call_id=call_id)])


async def _stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    del info
    step = _next(messages)
    if isinstance(step, str):
        yield step
        return
    call_id, name, args = step
    yield {0: DeltaToolCall(name, json.dumps(args, ensure_ascii=False), tool_call_id=call_id)}


def scripted_model() -> FunctionModel:
    """Новый экземпляр на прогон; сценарий не хранит состояние между пользователями."""
    return FunctionModel(_response, stream_function=_stream, model_name="scripted-test")
