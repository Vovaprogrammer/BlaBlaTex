"""Чат проекта и прогоны агента (architecture.md 8, 9.1): сообщения, прогон в очереди,
история чата, прогон, который идёт сейчас, отмена и прерванные прогоны."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode, request_error
from app.core.events import (
    EventPublisher,
    EventType,
    ProjectUnlockedData,
    RunFinishedData,
    RunUsage,
)
from app.modules.chat.models import ONE_ACTIVE_RUN_INDEX, AgentRun, ChatMessage
from app.modules.chat.schemas import (
    ACTIVE_RUN_STATUSES,
    ChangesetPart,
    ChatMessageOut,
    ErrorPart,
    RunOut,
    RunStatus,
    TextPart,
)
from app.modules.llm import service as llm_service
from app.modules.projects import history
from app.modules.projects import service as projects_service
from app.modules.projects.models import Project

_PROJECT_FK = "fk_agent_runs_project_id_projects"
RUN_NOT_FOUND_MESSAGE = "Запрос к ИИ не найден"
# Не «сервер перезапустился»: так же кончается прогон, чью блокировку воркер не продлил
# вовремя, хотя сервер работал.
RUN_INTERRUPTED_MESSAGE = "Прогон прервался. Отправьте сообщение ещё раз."
# Итог карточки инструмента, который не успел закончиться до конца прогона (9.1).
TOOL_INTERRUPTED_MESSAGE = (
    "Прервано: ИИ не успел закончить это действие. Отправьте сообщение ещё раз, чтобы продолжить."
)
TOOL_CANCELLED_MESSAGE = "Остановлено: вы остановили ИИ раньше, чем закончилось это действие."
# Прогон столько ждёт в очереди — его задание, видимо, потеряно, и воркеру оно уходит снова.
LOST_AFTER = timedelta(minutes=1)


@dataclass(frozen=True)
class NewRun:
    """Что создала отправка сообщения: сообщение студента, прогон и пустой ответ."""

    message: ChatMessage
    run: AgentRun
    reply: ChatMessage


async def create_message(
    session: AsyncSession, project: Project, user_id: uuid.UUID, text: str, settings: Settings
) -> NewRun:
    """Сообщение студента, прогон в очереди, его changeset и пустой ответ — одной
    транзакцией. Коммитит.

    Прогон проекта уже в очереди или идёт — 423 с его id: второй прогон не начинается.
    Это держит уникальный индекс, поэтому и два одновременных запроса не создадут два
    прогона. Дневная квота исчерпана, а своего ключа нет — 429 (architecture.md 8).
    Проект удалили — 404.
    """
    # После отката объекты сессии сброшены, и project.id в async уже не прочитать.
    project_id = project.id
    active = await _active_by_status(session, project_id)
    if active is not None:
        raise history.project_locked(active.id)
    await llm_service.ensure_quota(session, user_id, settings)
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


async def discard_run(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Удаляет прогон, который не удалось поставить в очередь, с его сообщениями и пустым
    changeset: без воркера он так и ждал бы в очереди. Коммитит.

    Прогон уже не в очереди — задание всё же дошло, и воркер его взял (или студент успел
    отменить): ничего не удаляется, False. Удалить идущий прогон нельзя — воркер держал бы
    проект прогоном, которого нет.
    """
    # Блокировка строки: воркер, который как раз берёт прогон, закончит раньше — или
    # увидит, что прогона нет. populate_existing: в сессии прогон ещё «в очереди».
    run = await session.get(AgentRun, run_id, with_for_update=True, populate_existing=True)
    if run is None:
        return True
    if run.status != "queued":
        # commit, а не rollback: менять нечего, а откат сбросил бы объекты сессии — их
        # ещё отдаёт ответ на POST /messages.
        await session.commit()
        return False
    changeset_id = run.changeset_id
    await session.execute(delete(ChatMessage).where(ChatMessage.run_id == run_id))
    await session.delete(run)
    await session.flush()
    if changeset_id is not None:
        await history.discard_empty_changeset(session, changeset_id)
    await session.commit()
    return True


async def find_active_run(session: AsyncSession, project_id: uuid.UUID) -> AgentRun | None:
    """Прогон проекта в очереди или идущий; такой у проекта не больше одного.

    Прогон running, чья блокировка истекла (воркер упал), — не активный: его скоро закроет
    фоновая проверка, а проект уже можно править.
    """
    run = await _active_by_status(session, project_id)
    if run is not None and run.status == "running":
        holders = await history.run_lock_holders(session, [project_id])
        if holders.get(project_id) != run.id:
            return None
    return run


async def _active_by_status(session: AsyncSession, project_id: uuid.UUID) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun).where(
            AgentRun.project_id == project_id, AgentRun.status.in_(ACTIVE_RUN_STATUSES)
        )
    )


@dataclass(frozen=True)
class ClosedRun:
    """Прогон, который закончился без агента: о нём нужно сообщить вкладкам."""

    project_id: uuid.UUID
    run_id: uuid.UUID
    changeset_id: uuid.UUID
    status: RunStatus


async def close_dead_runs(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> list[ClosedRun]:
    """Закрывает прогоны running, которые уже не держат свой проект: воркер упал, и срок
    блокировки истёк. Прогон — failed с RUN_INTERRUPTED_MESSAGE, ответу — карточка правок
    (если прогон успел что-то записать) и часть-ошибка, блокировка снимается. Агент второй
    раз не запускается. Коммитит.

    Блокируются строки только таких прогонов: живые прогоны проверка не задерживает.
    Прогон, который как раз записывает итог, пропускается (SKIP LOCKED): он закончится сам.
    """
    query = select(AgentRun).where(
        AgentRun.status == "running",
        AgentRun.changeset_id.is_not(None),
        ~history.holds_run_lock(AgentRun.project_id, AgentRun.id),
    )
    if project_id is not None:
        query = query.where(AgentRun.project_id == project_id)
    if run_id is not None:
        query = query.where(AgentRun.id == run_id)
    # populate_existing: прогон мог быть в сессии раньше, а читать нужно то, что в базе.
    runs = list(
        await session.scalars(
            query.with_for_update(skip_locked=True).execution_options(populate_existing=True)
        )
    )
    closed: list[ClosedRun] = []
    for run in runs:
        if run.changeset_id is None:  # отсеян запросом; проверка — для типов
            continue
        run.status = "failed"
        run.error = RUN_INTERRUPTED_MESSAGE
        run.finished_at = datetime.now(UTC)
        reply = await get_reply(session, run.id)
        if reply is not None:
            # Как в итоге воркера (runner._finish): что успел записать прогон, студент видит
            # в чате и может откатить.
            ending: list[BaseModel] = []
            if await history.changeset_has_writes(session, run.changeset_id):
                ending.append(ChangesetPart(changeset_id=run.changeset_id))
            ending.append(ErrorPart(text=RUN_INTERRUPTED_MESSAGE))
            reply.parts = [
                *interrupt_open_tools(reply.parts, "failed"),
                *(part.model_dump(mode="json") for part in ending),
            ]
        await history.release_run_lock(session, run.project_id, run.id)
        closed.append(ClosedRun(run.project_id, run.id, run.changeset_id, "failed"))
    await session.commit()
    return closed


# Any: части — JSON по схемам MessagePart, так они и лежат в chat_messages.parts.
def interrupt_open_tools(
    parts: Sequence[dict[str, Any]], status: RunStatus
) -> list[dict[str, Any]]:
    """Части ответа, где карточки инструментов без итога закрыты как прерванные (9.1):
    прогон закончился, и итога у них уже не будет. Без этого карточка вечно «работает»,
    и после перезагрузки тоже. Отдельного события нет: после run.finished вкладка
    перечитывает сообщения."""
    text = TOOL_CANCELLED_MESSAGE if status == "cancelled" else TOOL_INTERRUPTED_MESSAGE
    return [
        {**part, "ok": False, "result": text}
        if part["type"] == "tool" and part["ok"] is None
        else part
        for part in parts
    ]


async def publish_closed(events: EventPublisher, closed: list[ClosedRun]) -> None:
    """run.finished и project.unlocked для прогонов, закрытых без воркера."""
    for run in closed:
        await publish_finished(events, run, tokens_in=0, tokens_out=0)
        await events.publish(
            run.project_id, EventType.PROJECT_UNLOCKED, ProjectUnlockedData(run_id=run.run_id)
        )


async def publish_finished(
    events: EventPublisher, run: ClosedRun, *, tokens_in: int, tokens_out: int
) -> None:
    """run.finished: итог прогона для вкладок (9.3)."""
    await events.publish(
        run.project_id,
        EventType.RUN_FINISHED,
        RunFinishedData(
            run_id=run.run_id,
            status=run.status,
            changeset_id=run.changeset_id,
            usage=RunUsage(tokens_in=tokens_in, tokens_out=tokens_out),
        ),
    )


async def lost_queued_runs(session: AsyncSession) -> list[uuid.UUID]:
    """Прогоны, которые дольше LOST_AFTER ждут в очереди: их задание, видимо, потеряно."""
    result = await session.scalars(
        select(AgentRun.id).where(
            AgentRun.status == "queued", AgentRun.created_at < func.now() - LOST_AFTER
        )
    )
    return list(result)


async def get_owned_run(
    session: AsyncSession, run_id: uuid.UUID, owner_id: uuid.UUID
) -> AgentRun | None:
    """Прогон из проекта владельца или None: чужой и несуществующий не различаются."""
    run = await session.get(AgentRun, run_id)
    if run is None:
        return None
    project = await projects_service.get_owned_project(session, run.project_id, owner_id)
    return run if project is not None else None


async def cancel_run(session: AsyncSession, run: AgentRun) -> ClosedRun | None:
    """Отмена прогона студентом. Коммитит.

    В очереди — сразу cancelled; он и возвращается, чтобы вызывающий послал run.finished.
    Идущему ставится отметка cancel_requested_at: воркер увидит её не позже чем через
    секунду и остановит агента (runner). Законченный не меняется.
    """
    run_id = run.id
    cancelled = await session.scalar(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == "queued")
        .values(status="cancelled", finished_at=func.now())
        .returning(AgentRun.id)
    )
    if cancelled is None:
        await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == "running",
                AgentRun.cancel_requested_at.is_(None),
            )
            .values(cancel_requested_at=func.now())
        )
    await session.commit()
    await session.refresh(run)
    if cancelled is None or run.changeset_id is None:
        return None
    return ClosedRun(run.project_id, run_id, run.changeset_id, "cancelled")


async def stop_run(session: AsyncSession, events: EventPublisher, run: AgentRun) -> None:
    """POST /runs/{rid}/cancel: отмена и события о ней. Коммитит.

    Прогон, чей воркер упал (блокировка истекла), закрывается сразу как прерванный: иначе
    отметку отмены некому увидеть, и студент ждал бы фоновую проверку до 30 с.
    """
    closed = await close_dead_runs(session, run_id=run.id)
    if closed:
        await publish_closed(events, closed)
    else:
        cancelled = await cancel_run(session, run)
        if cancelled is not None:
            await publish_finished(events, cancelled, tokens_in=0, tokens_out=0)
    await session.refresh(run)


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
    reply = await get_reply(session, run.id)
    if reply is None or run.changeset_id is None:
        raise RuntimeError(f"У прогона {run.id} нет ответа или changeset")
    return RunOut(
        id=run.id,
        status=run.status,
        message_id=reply.id,
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


async def get_reply(session: AsyncSession, run_id: uuid.UUID) -> ChatMessage | None:
    """Ответ ассистента прогона."""
    return await session.scalar(
        select(ChatMessage).where(ChatMessage.run_id == run_id, ChatMessage.role == "assistant")
    )


async def _raise_if_taken(
    session: AsyncSession, project_id: uuid.UUID, error: IntegrityError
) -> None:
    """Прогон проекта создали одновременно с этим — 423; проект удалили — 404."""
    if ONE_ACTIVE_RUN_INDEX in str(error.orig):
        active = await _active_by_status(session, project_id)
        if active is not None:
            raise history.project_locked(active.id) from None
    if _PROJECT_FK in str(error.orig):
        raise AppError(
            ErrorCode.NOT_FOUND, projects_service.PROJECT_NOT_FOUND_MESSAGE, 404
        ) from None
