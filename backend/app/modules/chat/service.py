"""Чат проекта и прогоны агента (architecture.md 8, 9.1): сообщения, прогон в очереди,
история чата и прогон, который идёт сейчас."""

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, request_error
from app.modules.chat.models import ONE_ACTIVE_RUN_INDEX, AgentRun, ChatMessage
from app.modules.chat.schemas import (
    ACTIVE_RUN_STATUSES,
    ChatMessageOut,
    RunOut,
    RunStatus,
    TextPart,
)
from app.modules.projects import history
from app.modules.projects.models import Project
from app.modules.projects.service import PROJECT_NOT_FOUND_MESSAGE

_PROJECT_FK = "fk_agent_runs_project_id_projects"


@dataclass(frozen=True)
class NewRun:
    """Что создала отправка сообщения: сообщение студента, прогон и пустой ответ."""

    message: ChatMessage
    run: AgentRun
    reply: ChatMessage


async def create_message(
    session: AsyncSession, project: Project, user_id: uuid.UUID, text: str
) -> NewRun:
    """Сообщение студента, прогон в очереди, его changeset и пустой ответ — одной
    транзакцией. Коммитит.

    Прогон проекта уже в очереди или идёт — 423 с его id: второй прогон не начинается.
    Это держит уникальный индекс, поэтому и два одновременных запроса не создадут два
    прогона. Проект удалили — 404.
    """
    # После отката объекты сессии сброшены, и project.id в async уже не прочитать.
    project_id = project.id
    active = await find_active_run(session, project_id)
    if active is not None:
        raise history.project_locked(active.id)
    try:
        run = AgentRun(project_id=project_id, user_id=user_id, status="queued")
        session.add(run)
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        await _raise_if_taken(session, project_id, error)
        raise
    # Changeset ссылается на прогон, а прогон — на changeset: сначала строка прогона.
    changeset = await history.create_changeset(session, project_id, "ai", user_id, run_id=run.id)
    run.changeset_id = changeset.id
    message = ChatMessage(
        project_id=project_id,
        run_id=run.id,
        role="user",
        parts=[TextPart(text=text).model_dump(mode="json")],
    )
    session.add(message)
    # Ответ создаётся сразу: у каждого прогона ровно один ответ, и его id знают события.
    reply = ChatMessage(project_id=project_id, run_id=run.id, role="assistant")
    session.add(reply)
    await session.commit()
    return NewRun(message=message, run=run, reply=reply)


async def discard_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Удаляет прогон, который не удалось поставить в очередь, с его сообщениями и пустым
    changeset: без воркера он так и ждал бы в очереди. Коммитит."""
    run = await session.get(AgentRun, run_id)
    if run is None:
        return
    changeset_id = run.changeset_id
    await session.execute(delete(ChatMessage).where(ChatMessage.run_id == run_id))
    await session.delete(run)
    await session.flush()
    if changeset_id is not None:
        await history.discard_empty_changeset(session, changeset_id)
    await session.commit()


async def find_active_run(session: AsyncSession, project_id: uuid.UUID) -> AgentRun | None:
    """Прогон проекта в очереди или идущий; такой у проекта не больше одного."""
    return await session.scalar(
        select(AgentRun).where(
            AgentRun.project_id == project_id, AgentRun.status.in_(ACTIVE_RUN_STATUSES)
        )
    )


async def list_messages(
    session: AsyncSession, project_id: uuid.UUID, *, before: uuid.UUID | None, limit: int
) -> tuple[list[ChatMessageOut], bool]:
    """Последние limit сообщений чата до before, старые первыми, и есть ли раньше.

    before — первое сообщение предыдущей страницы; нет его в чате проекта — 422.
    """
    query = (
        select(ChatMessage, AgentRun.status)
        # Статус — только у ответа: сообщение студента тоже ссылается на прогон.
        .outerjoin(
            AgentRun,
            and_(AgentRun.id == ChatMessage.run_id, ChatMessage.role == "assistant"),
        )
        # system в API не отдаётся (раздел 5): такие сообщения пока не создаются.
        .where(ChatMessage.project_id == project_id, ChatMessage.role != "system")
    )
    if before is not None:
        position = await session.scalar(
            select(ChatMessage.position).where(
                ChatMessage.id == before, ChatMessage.project_id == project_id
            )
        )
        if position is None:
            raise request_error(["query", "before"], "Такого сообщения нет в чате проекта")
        query = query.where(ChatMessage.position < position)
    rows = list(
        (await session.execute(query.order_by(ChatMessage.position.desc()).limit(limit + 1))).all()
    )
    has_more = len(rows) > limit
    page = [message_out(message, status) for message, status in reversed(rows[:limit])]
    return page, has_more


async def run_out(session: AsyncSession, run: AgentRun) -> RunOut:
    """Прогон для API: с id его ответа."""
    reply_id = await session.scalar(
        select(ChatMessage.id).where(ChatMessage.run_id == run.id, ChatMessage.role == "assistant")
    )
    if reply_id is None or run.changeset_id is None:
        raise RuntimeError(f"У прогона {run.id} нет ответа или changeset")
    return RunOut(
        id=run.id,
        status=run.status,
        message_id=reply_id,
        changeset_id=run.changeset_id,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


def message_out(message: ChatMessage, run_status: RunStatus | None) -> ChatMessageOut:
    """Сообщение для API; run_status — статус прогона ответа, у сообщения студента — None."""
    return ChatMessageOut(
        id=message.id,
        role=message.role,
        run_id=message.run_id,
        status=run_status if message.role == "assistant" else None,
        parts=message.parts,
        seq=message.seq,
        created_at=message.created_at,
    )


async def _raise_if_taken(
    session: AsyncSession, project_id: uuid.UUID, error: IntegrityError
) -> None:
    """Прогон проекта создали одновременно с этим — 423; проект удалили — 404."""
    if ONE_ACTIVE_RUN_INDEX in str(error.orig):
        active = await find_active_run(session, project_id)
        if active is not None:
            raise history.project_locked(active.id) from None
    if _PROJECT_FK in str(error.orig):
        raise AppError(ErrorCode.NOT_FOUND, PROJECT_NOT_FOUND_MESSAGE, 404) from None
