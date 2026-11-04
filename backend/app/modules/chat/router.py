"""Чат проекта и прогоны агента (architecture.md 8, 9.1)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.errors import not_implemented
from app.modules.auth.dependencies import CurrentUser
from app.modules.chat.schemas import (
    MESSAGES_DEFAULT_LIMIT,
    MESSAGES_MAX_LIMIT,
    MessageCreate,
    MessageCreated,
    MessageList,
    RunOut,
)
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.schemas import LOCKED_RESPONSES

router = APIRouter(prefix="/projects", tags=["chat"])


@router.get("/{pid}/messages")
async def list_messages(
    project: OwnedProject,
    before: Annotated[
        UUID | None, Query(description="id первого сообщения предыдущей страницы")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MESSAGES_MAX_LIMIT)] = MESSAGES_DEFAULT_LIMIT,
) -> MessageList:
    """Чат проекта: последние limit сообщений, старые первыми, и прогон, который идёт сейчас.

    Более ранние — before=<id первого в списке>; такого сообщения в чате проекта нет — 422.
    """
    raise not_implemented()


@router.post("/{pid}/messages", status_code=201, responses=LOCKED_RESPONSES)
async def post_message(body: MessageCreate, project: OwnedProject) -> MessageCreated:
    """Сообщение студента и прогон агента в очереди.

    Прогон проекта уже идёт или ждёт — 423; очередь недоступна — 500, ничего не сохраняется.
    """
    raise not_implemented()


# Прогон адресуется сам по себе, без проекта в пути: /runs/{rid}/...
runs_router = APIRouter(prefix="/runs", tags=["chat"])


@runs_router.post("/{rid}/cancel")
async def cancel_run(rid: UUID, user: CurrentUser) -> RunOut:
    """Останавливает прогон: в очереди — сразу, идущий — не позже чем через 5 с.

    Законченный прогон возвращается как есть; прогон чужого проекта — 404.
    """
    raise not_implemented()
