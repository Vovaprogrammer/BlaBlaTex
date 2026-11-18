"""Составление плана отчёта моделью по контракту 9.4."""

import asyncio
import json
from contextlib import suppress

import structlog
from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent, RunContext, ToolReturn
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RunUsage, UsageLimits

from app.modules.agent.contract import PlanRequest, PlanResult
from app.modules.agent.models import get_model
from app.modules.agent.prompt_loader import render_plan_instructions
from app.modules.agent.runner import CONFIG_ERROR, LIMIT_ERROR, MODEL_ERROR, TOOL_RETRIES, _usage
from app.modules.plans.schemas import PlanSection, ReportPlan
from app.modules.projects.tools import DEFAULT_MATERIAL_LIMIT, ToolError

logger = structlog.get_logger(__name__)


class PlannedSection(BaseModel):
    section_id: str = Field(description="Идентификатор раздела из шаблона")
    materials: list[str] = Field(description="Пути использованных материалов")
    note: str = Field(description="Что написать и какие сведения отсутствуют", repr=False)


class PlannedSections(BaseModel):
    sections: list[PlannedSection]


def _register_tools(agent: Agent[PlanRequest, PlannedSections]) -> None:
    @agent.tool
    async def read_material(
        ctx: RunContext[PlanRequest],
        path: str,
        offset: int = 0,
        limit: int = DEFAULT_MATERIAL_LIMIT,
    ) -> object:
        """Прочитать извлечённый текст материала по пути и смещению в символах."""
        try:
            return await ctx.deps.tools.read_material(path, offset, limit)
        except ToolError as exc:
            return exc.message

    @agent.tool
    async def get_image(ctx: RunContext[PlanRequest], path: str) -> ToolReturn[str] | str:
        """Посмотреть изображение материала PNG или JPEG."""
        try:
            image = await ctx.deps.tools.get_image(path)
        except ToolError as exc:
            return exc.message
        return ToolReturn(
            return_value="Изображение приложено.",
            content=[BinaryContent(data=image.data, media_type=image.mime)],
        )


async def make_plan(request: PlanRequest) -> PlanResult:
    """Составить план без записи файлов и событий прогона."""
    usage = RunUsage()
    messages: list[ModelMessage] = []
    if request.cancel.is_set():
        return PlanResult(status="cancelled", usage=_usage(usage, messages, ""))
    try:
        model = get_model("main", request.user_key)
    except ValueError:
        return PlanResult(status="failed", error=CONFIG_ERROR, usage=_usage(usage, messages, ""))

    agent = Agent(
        model,
        deps_type=PlanRequest,
        output_type=PlannedSections,
        instructions=render_plan_instructions(),
        retries={"tools": TOOL_RETRIES},
    )
    _register_tools(agent)
    history = [
        ModelRequest(parts=[UserPromptPart(message.text)])
        if message.role == "user"
        else ModelResponse(parts=[TextPart(message.text)])
        for message in request.history[:-1]
    ]
    data = json.dumps(
        {
            "guide": request.guide.model_dump(mode="json"),
            "materials": [material.model_dump(mode="json") for material in request.materials],
        },
        ensure_ascii=False,
    )
    prompt = f"{request.history[-1].text}\n\nШаблон и материалы проекта:\n{data}"
    status = "done"
    error = None
    plan = None
    async with agent:

        async def run_model() -> PlannedSections:
            async with agent.iter(
                prompt,
                message_history=history,
                deps=request,
                usage=usage,
                usage_limits=UsageLimits(total_tokens_limit=request.max_tokens),
            ) as run:
                try:
                    async for _ in run:
                        pass
                    if run.result is None:
                        raise RuntimeError("Модель завершилась без результата")
                    return run.result.output
                finally:
                    messages[:] = run.new_messages()

        task = asyncio.create_task(run_model())
        watcher = asyncio.create_task(request.cancel.wait())
        try:
            await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
            if request.cancel.is_set():
                status = "cancelled"
                task.cancel()
                # Одновременно с отменой задача может завершиться ошибкой провайдера.
                with suppress(asyncio.CancelledError, Exception):
                    await task
            else:
                output = await task
                plan = ReportPlan(
                    sections=[
                        PlanSection(
                            section_id=s.section_id, title="", materials=s.materials, note=s.note
                        )
                        for s in output.sections
                    ],
                    unassigned=[],
                )
        except UsageLimitExceeded:
            status, error = "failed", LIMIT_ERROR
        except (ModelAPIError, FallbackExceptionGroup, UnexpectedModelBehavior) as exc:
            status, error = "failed", MODEL_ERROR
            logger.warning(
                "plan_model_failed",
                run_id=str(request.run_id),
                project_id=str(request.context.project_id),
                error_type=type(exc).__name__,
            )
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
    if request.cancel.is_set():
        status, error, plan = "cancelled", None, None
    return PlanResult(
        status=status, plan=plan, error=error, usage=_usage(usage, messages, model.model_name)
    )
