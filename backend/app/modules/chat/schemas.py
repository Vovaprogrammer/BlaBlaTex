"""Схемы чата и прогонов агента (architecture.md 9.1 «Чат и прогоны агента»)."""

from datetime import datetime
from typing import Annotated, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.core.text import NoNul

RunStatus = Literal["queued", "running", "done", "failed", "cancelled"]
# Прогон в очереди или идущий: у проекта такой не больше одного.
ActiveRunStatus = Literal["queued", "running"]
ACTIVE_RUN_STATUSES: tuple[ActiveRunStatus, ...] = get_args(ActiveRunStatus)
MessageRole = Literal["user", "assistant"]

MESSAGE_MAX_LENGTH = 10_000


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolPart(BaseModel):
    """Карточка вызова инструмента: run.tool_call, а потом его итог из run.tool_result."""

    type: Literal["tool"] = "tool"
    call_id: str = Field(description="id вызова у модели")
    tool: str
    summary: str = Field(description="Что делает вызов — из run.tool_call")
    ok: bool | None = Field(
        default=None,
        description="Итог; false — ошибка или прогон закончился раньше инструмента; "
        "null — инструмент ещё работает",
    )
    result: str | None = Field(
        default=None,
        description="Короткий итог из run.tool_result или почему инструмент прерван; "
        "null — итога ещё нет",
    )


class ChangesetPart(BaseModel):
    """Карточка правок прогона: есть, только если прогон что-то записал."""

    type: Literal["changeset"] = "changeset"
    changeset_id: UUID


class ErrorPart(BaseModel):
    type: Literal["error"] = "error"
    text: str = Field(description="Понятная ошибка прогона")


MessagePart = Annotated[
    TextPart | ToolPart | ChangesetPart | ErrorPart, Field(discriminator="type")
]


class ChatMessageOut(BaseModel):
    id: UUID
    role: MessageRole
    run_id: UUID | None = Field(description="Прогон, который начат сообщением или дал ответ")
    status: RunStatus | None = Field(
        description="У ответа ассистента — статус его прогона, у сообщения студента — null"
    )
    parts: list[MessagePart] = Field(description="Части сообщения по порядку")
    seq: int = Field(
        description="Номер последнего события прогона, которое уже вошло в parts; "
        "у сообщения студента — 0"
    )
    created_at: datetime


class RunOut(BaseModel):
    id: UUID
    status: RunStatus
    message_id: UUID = Field(description="Ответ ассистента этого прогона")
    changeset_id: UUID = Field(description="Changeset, куда пишет агент")
    error: str | None = Field(description="Текст ошибки при failed, иначе null")
    created_at: datetime
    finished_at: datetime | None


class MessageList(BaseModel):
    items: list[ChatMessageOut] = Field(description="По порядку, старые первыми")
    has_more: bool = Field(description="Есть ли раньше: следующая страница — before=<id первого>")
    active_run: RunOut | None = Field(
        description="Прогон в очереди или идущий; status=running — проект заблокирован"
    )


MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MESSAGE_MAX_LENGTH),
    NoNul,
]


class MessageCreate(BaseModel):
    text: MessageText


class MessageCreated(BaseModel):
    message: ChatMessageOut = Field(description="Сообщение студента")
    run: RunOut = Field(description="Прогон в очереди")
