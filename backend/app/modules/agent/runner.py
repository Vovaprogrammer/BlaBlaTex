"""Потоковый прогон агента по контракту 9.4."""

import asyncio
from contextlib import suppress
from decimal import Decimal

from pydantic_ai import Agent
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    RunCancelled,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage, UsageLimits

from app.core.config import get_settings
from app.modules.agent.contract import ModelUsage, RunRequest, RunResult, RunStatus
from app.modules.agent.models import get_model
from app.modules.agent.tools import register_tools

LIMIT_ERROR = "Превышен лимит токенов прогона."
MODEL_ERROR = "Модель сейчас недоступна. Попробуйте ещё раз."
CONFIG_ERROR = "Модель для чата не настроена."


async def run_agent(request: RunRequest) -> RunResult:
    """Запускает агента с инструментами проекта и публикует текст по мере получения."""
    usage = RunUsage()
    messages: list[ModelMessage] = []
    chunks: list[str] = []
    status: RunStatus = "done"
    error: str | None = None
    if request.cancel.is_set():
        return RunResult(status="cancelled", text="", usage=_usage(usage, messages, ""))
    try:
        model = get_model("main", request.user_key)
    except ValueError:
        return RunResult(
            status="failed", text="", error=CONFIG_ERROR, usage=_usage(usage, messages, "")
        )

    agent = Agent(model, deps_type=RunRequest)
    register_tools(agent)
    history = [
        ModelRequest(parts=[UserPromptPart(message.text)])
        if message.role == "user"
        else ModelResponse(parts=[TextPart(message.text)])
        for message in request.history[:-1]
    ]
    async with (
        agent,
        agent.run_stream_events(
            request.history[-1].text,
            message_history=history,
            deps=request,
            usage=usage,
            usage_limits=UsageLimits(total_tokens_limit=request.max_tokens),
        ) as stream,
    ):

        async def cancel_on_request() -> None:
            await request.cancel.wait()
            stream.cancel()

        watcher = asyncio.create_task(cancel_on_request())
        try:
            async for event in stream:
                if request.cancel.is_set():
                    stream.cancel()
                    break
                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                    delta = event.part.content
                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                    delta = event.delta.content_delta
                else:
                    continue
                if delta:
                    chunks.append(delta)
                    await request.events.delta(delta)
        except RunCancelled:
            status = "cancelled"
        except UsageLimitExceeded:
            status, error = "failed", LIMIT_ERROR
        except (ModelAPIError, FallbackExceptionGroup, UnexpectedModelBehavior):
            status, error = "failed", MODEL_ERROR
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
        # При ранней отмене граф мог ещё не начать выполнение.
        if usage.requests:
            messages = stream.new_messages()
    if request.cancel.is_set():
        status, error = "cancelled", None
    return RunResult(
        status=status,
        text="".join(chunks),
        error=error,
        usage=_usage(usage, messages, model.model_name),
    )


def _usage(usage: RunUsage, messages: list[ModelMessage], model_name: str) -> ModelUsage:
    """Оценивает стоимость каждого ответа по тарифу фактического провайдера."""
    settings = get_settings()
    provider_names = (settings.llm_default_provider, settings.llm_fallback_provider)
    rates = [
        (str(provider.base_url).rstrip("/"), provider.models["main"])
        for name in provider_names
        if name is not None
        for provider in (settings.llm_providers[name],)
    ]
    cost = Decimal(0)
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        model_name = message.model_name or model_name
        url = (message.provider_url or "").rstrip("/")
        candidates = [price for base_url, price in rates if base_url == url]
        price = next((price for price in candidates if price.name == message.model_name), None)
        if price is None and len(candidates) == 1:
            price = candidates[0]
        if price is not None:
            cost += price.input_price * message.usage.input_tokens
            cost += price.output_price * message.usage.output_tokens
    return ModelUsage(
        model=model_name[:100],
        tokens_in=usage.input_tokens,
        tokens_out=usage.output_tokens,
        cost=cost / 1_000_000,
    )
