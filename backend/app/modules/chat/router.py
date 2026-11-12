"""Чат проекта и прогоны агента (architecture.md 8, 9.1)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.core.db import DbSession
from app.core.events import EventsDep
from app.core.ratelimit import Limit, get_rate_limiter
from app.modules.auth.dependencies import CurrentUser
from app.modules.chat import service, tasks
from app.modules.chat.dependencies import OwnedRun, RunEnqueue
from app.modules.chat.schemas import (
    MESSAGES_DEFAULT_LIMIT,
    MESSAGES_MAX_LIMIT,
    MessageCreate,
    MessageCreated,
    MessageList,
    RunOut,
)
from app.modules.llm.dependencies import AppSettings
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.schemas import LOCKED_RESPONSES

router = APIRouter(prefix="/projects", tags=["chat"])

# Сообщений на студента, по всем проектам вместе (9.1). Со своим ключом квоты нет, и без
# лимита скрипт запускал бы прогон за прогоном в десятке проектов, занимая воркер всем.
MESSAGES_LIMIT = Limit(count=20, period_s=10 * 60)


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
    settings: AppSettings,
    request: Request,
) -> MessageCreated:
    """Сообщение студента и прогон агента в очереди.

    Больше 20 сообщений за 10 минут — 429 rate_limited; прогон проекта уже идёт или
    ждёт — 423; дневная квота исчерпана, а своего ключа нет — 429 quota_exceeded; очередь
    недоступна — 500. В этих случаях ничего не сохраняется.
    """
    await get_rate_limiter(request).check("messages", str(user.id), MESSAGES_LIMIT)
    created = await tasks.post_message(
        session, events, project, user.id, body.text, settings, enqueue
    )
    return MessageCreated(
        message=service.message_out(created.message, None),
        run=await service.run_out(session, created.run),
    )


# Прогон адресуется сам по себе, без проекта в пути: /runs/{rid}/...
runs_router = APIRouter(prefix="/runs", tags=["chat"])


@runs_router.post("/{rid}/cancel")
async def cancel_run(run: OwnedRun, session: DbSession, events: EventsDep) -> RunOut:
    """Останавливает прогон: в очереди — сразу, идущий — не позже чем через 5 с, его итог
    придёт событием run.finished.

    Законченный прогон возвращается как есть; прогон чужого проекта — 404.
    """
    await service.stop_run(session, events, run)
    return await service.run_out(session, run)
