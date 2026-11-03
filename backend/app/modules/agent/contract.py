"""Точки входа агента (architecture.md 9.4): что бэкенд передаёт агенту и что получает обратно.

Здесь только типы. run_agent и describe_image реализует зона ИИ (A2.1, A2.4), а до этого
бэкенд вызывает заглушки (B2.6, B2.7). Фейк RunEvents для тестов — tests/fake_run_events.py.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field, SecretStr

from app.modules.projects.tools import ProjectTools, ToolContext

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


class DescribeImage(Protocol):
    """Сигнатура describe_image (A2.4). При сбое модели — исключение: описание остаётся
    пустым (B2.7)."""

    async def __call__(
        self, data: bytes, mime: str, *, user_key: SecretStr | None = None
    ) -> ImageDescription: ...
