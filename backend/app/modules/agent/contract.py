"""Точки входа агента (architecture.md 9.4): что бэкенд передаёт агенту и что получает обратно.

Здесь только типы. run_agent, make_plan и describe_image реализует зона ИИ (A2.1, A3.1, A2.4),
а до этого бэкенд вызывает заглушки (B2.6, B3.8, B2.7). Фейк RunEvents для тестов —
tests/fake_run_events.py.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field, SecretStr

from app.modules.plans.schemas import ReportPlan
from app.modules.projects.tools import (
    DEFAULT_MATERIAL_LIMIT,
    ImageData,
    MaterialInfo,
    MaterialText,
    ProjectTools,
    TemplateGuide,
    ToolContext,
)

RunStatus = Literal["done", "failed", "cancelled"]


class HistoryMessage(BaseModel):
    """Сообщение чата для агента."""

    role: Literal["user", "assistant"]
    # Текст студента не попадает ни в repr, ни в логи.
    text: str = Field(repr=False)


class RunEvents(Protocol):
    """События прогона, которые шлёт агент (9.3). run_id и message_id добавляет бэкенд.

    run.started, run.finished и блокировку проекта шлёт сам бэкенд.
    """

    async def delta(self, text: str) -> None:
        """Кусок ответа модели — run.delta."""
        ...

    async def tool_call(self, call_id: str, tool: str, summary: str) -> None:
        """Модель вызвала инструмент — run.tool_call; call_id — id вызова у модели."""
        ...

    async def tool_result(self, call_id: str, ok: bool, summary: str) -> None:
        """Итог инструмента — run.tool_result; ok=False, если он вернул ToolError."""
        ...


@dataclass(frozen=True)
class RunRequest:
    """Вход run_agent: всё, что агенту нужно на один прогон."""

    # Прогон (agent_runs.id): по нему ищут сбой в логах. Только id, без текста.
    run_id: uuid.UUID
    # Сообщения чата по порядку, последнее — запрос пользователя. Это текст студента,
    # поэтому история, как и ключ, не попадает в repr и логи.
    history: Sequence[HistoryMessage] = field(repr=False)
    context: ToolContext
    tools: ProjectTools
    events: RunEvents
    # Бэкенд взводит его по POST /runs/{rid}/cancel. Агент проверяет его между шагами
    # и во время стрима и возвращает status=cancelled.
    cancel: asyncio.Event
    # Лимит токенов на прогон: вход и выход вместе. Превышение — status=failed.
    max_tokens: int
    # Свой ключ LLM пользователя (B3.1); без него — ключ сервиса.
    user_key: SecretStr | None = field(default=None, repr=False)
    # Подтверждённый план отчёта (B3.8) — у прогона kind=report, иначе None. В нём заметки
    # студента, поэтому он, как и история, не попадает в repr и логи.
    plan: ReportPlan | None = field(default=None, repr=False)


class PlanTools(Protocol):
    """Часть ProjectTools, которая нужна для плана: make_plan материалы только читает."""

    async def read_material(
        self, path: str, offset: int = 0, limit: int = DEFAULT_MATERIAL_LIMIT
    ) -> MaterialText:
        """Кусок извлечённого текста материала: не больше limit символов с offset."""
        ...

    async def get_image(self, path: str) -> ImageData:
        """Картинка .png, .jpg или .jpeg."""
        ...


@dataclass(frozen=True)
class PlanRequest:
    """Вход make_plan (B3.8, A3.1): всё, что нужно, чтобы составить план отчёта."""

    run_id: uuid.UUID
    # Сообщения чата по порядку, последнее — «Составь план отчёта». Как в RunRequest, не
    # попадает в repr и логи.
    history: Sequence[HistoryMessage] = field(repr=False)
    # Разделы шаблона и что в них писать — как get_template_guide.
    guide: TemplateGuide
    # Материалы проекта — как list_materials. Текст — через tools.read_material.
    materials: Sequence[MaterialInfo]
    context: ToolContext
    tools: PlanTools
    cancel: asyncio.Event
    max_tokens: int
    user_key: SecretStr | None = field(default=None, repr=False)


class ModelUsage(BaseModel):
    """Расход на вызовы модели: бэкенд пишет его в agent_runs и usage (B3.1)."""

    model: str
    tokens_in: int
    tokens_out: int
    cost: Decimal


class RunResult(BaseModel):
    status: RunStatus
    text: str = Field(description="Ответ ассистента; при отмене — то, что успело прийти")
    error: str | None = Field(
        default=None, description="Сообщение для пользователя при failed, иначе null"
    )
    usage: ModelUsage


class PlanResult(BaseModel):
    status: RunStatus
    # Заметки плана написаны по материалам студента — в repr не попадают.
    plan: ReportPlan | None = Field(
        default=None, repr=False, description="План при done, иначе null"
    )
    error: str | None = Field(
        default=None, description="Сообщение для пользователя при failed, иначе null"
    )
    usage: ModelUsage


class ImageDescription(BaseModel):
    text: str
    usage: ModelUsage


class RunAgent(Protocol):
    """Сигнатура run_agent (A2.1).

    Сбой модели и превышение max_tokens — status=failed с понятным error, а не исключение.
    ToolError возвращается модели как результат инструмента. Другие исключения выходят
    наружу: бэкенд помечает прогон failed с общим сообщением.
    """

    async def __call__(self, request: RunRequest) -> RunResult: ...


class MakePlan(Protocol):
    """Сигнатура make_plan (A3.1): раскладывает материалы по разделам шаблона.

    Файлы не пишет и событий не шлёт: ответ в чате пишет бэкенд. Отмена, сбой модели,
    max_tokens и исключения — как у run_agent. title и unassigned бэкенд считает сам.
    """

    async def __call__(self, request: PlanRequest) -> PlanResult: ...


class DescribeImage(Protocol):
    """Сигнатура describe_image (A2.4). При сбое модели — исключение: описание остаётся
    пустым (B2.7)."""

    async def __call__(
        self, data: bytes, mime: str, *, user_key: SecretStr | None = None
    ) -> ImageDescription: ...
