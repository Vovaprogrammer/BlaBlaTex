"""Чат проекта и прогоны агента (architecture.md 8, 9.1)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.core.events import EventsDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.chat import service, tasks
from app.modules.chat.dependencies import RunEnqueue
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
    session: DbSession,
    before: Annotated[
        UUID | None, Query(description="id первого сообщения предыдущей страницы")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MESSAGES_MAX_LIMIT)] = MESSAGES_DEFAULT_LIMIT,
) -> MessageList:
    """Чат проекта: последние limit сообщений, старые первыми, и прогон, который идёт сейчас.

    Более ранние — before=<id первого в списке>; такого сообщения в чате проекта нет — 422.
    """
    items, has_more = await service.list_messages(session, project.id, before=before, limit=limit)
    active = await service.find_active_run(session, project.id)
    return MessageList(
        items=items,
        has_more=has_more,
        active_run=None if active is None else await service.run_out(session, active),
    )


@router.post("/{pid}/messages", status_code=201, responses=LOCKED_RESPONSES)
async def post_message(
    body: MessageCreate,
    project: OwnedProject,
    user: CurrentUser,
    session: DbSession,
    events: EventsDep,
    enqueue: RunEnqueue,
) -> MessageCreated:
    """Сообщение студента и прогон агента в очереди.

    Прогон проекта уже идёт или ждёт — 423; очередь недоступна — 500, ничего не сохраняется.
    """
    created = await tasks.post_message(session, events, project, user.id, body.text, enqueue)
    return MessageCreated(
        message=service.message_out(created.message, None),
        run=await service.run_out(session, created.run),
    )


# Прогон адресуется сам по себе, без проекта в пути: /runs/{rid}/...
runs_router = APIRouter(prefix="/runs", tags=["chat"])


@runs_router.post("/{rid}/cancel")
async def cancel_run(rid: UUID, user: CurrentUser, session: DbSession, events: EventsDep) -> RunOut:
    """Останавливает прогон: в очереди — сразу, идущий — не позже чем через 5 с, его итог
    придёт событием run.finished.

    Законченный прогон возвращается как есть; прогон чужого проекта — 404.
    """
    run = await service.get_owned_run(session, rid, user.id)
    if run is None:
        raise AppError(ErrorCode.NOT_FOUND, service.RUN_NOT_FOUND_MESSAGE, 404)
    cancelled = await service.cancel_run(session, run)
    if cancelled is not None:
        await service.publish_finished(events, cancelled, tokens_in=0, tokens_out=0)
    return await service.run_out(session, run)
