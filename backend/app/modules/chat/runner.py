"""Прогон агента в воркере (architecture.md 8, 9.3, 9.4).

Задание прогона берёт прогон из очереди, занимает проект, собирает историю чата,
вызывает run_agent с настоящими ProjectTools и записывает итог: статус и расход
в agent_runs, части ответа в сообщение ассистента, снятие блокировки — одной транзакцией.
События project.locked, run.started, run.finished и project.unlocked шлёт сам; run.delta,
run.tool_call и run.tool_result шлёт агент через RunEvents, а бэкенд добавляет к ним
run_id, message_id и номер seq и складывает их в части ответа.

Пока агент работает, воркер раз в секунду сохраняет части ответа и проверяет отмену,
а раз в 10 секунд продлевает блокировку проекта.
"""

import asyncio
import copy
import time
import uuid
from collections.abc import Coroutine, Sequence
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import (
    EventPublisher,
    EventType,
    ProjectLockedData,
    ProjectUnlockedData,
    RunDeltaData,
    RunStartedData,
    RunToolCallData,
    RunToolResultData,
)
from app.core.storage import Storage
from app.modules.agent.contract import HistoryMessage, RunAgent, RunRequest, RunResult, RunStatus
from app.modules.chat import service
from app.modules.chat.models import AgentRun, ChatMessage
from app.modules.chat.schemas import ChangesetPart, ErrorPart, TextPart, ToolPart
from app.modules.projects import history
from app.modules.projects.service_tools import ServiceProjectTools
from app.modules.projects.tools import ToolContext
from app.modules.templates.registry import Registry

logger = structlog.get_logger(__name__)

# История для агента: столько сообщений до запроса и сам запрос.
HISTORY_MESSAGES = 20
# Старое сообщение длиннее этого агент видит сокращённым: длинные ответы прошлых прогонов
# занимали бы токены, а нужно агенту в основном начало.
HISTORY_MESSAGE_MAX_CHARS = 4000
SHORTENED_MARK = "… (сообщение сокращено)"
RUN_FAILED_MESSAGE = "Не удалось выполнить запрос. Попробуйте ещё раз."


@dataclass(frozen=True)
class RunTiming:
    """Сроки присмотра за агентом. В тестах — короче."""

    # Как часто сохранять части ответа и проверять отмену. Отмена доходит до агента не
    # позже чем через tick_s, а вкладка, открытая посреди прогона, видит ответ без
    # отставания больше tick_s.
    tick_s: float = 1.0
    # Как часто продлевать блокировку проекта: втрое чаще её срока (history.RUN_LOCK_TTL),
    # чтобы пара сбоев подряд её не потеряла.
    renew_s: float = 10.0
    # Сколько ждать агента после отмены, прежде чем прервать его. С tick_s прогон
    # останавливается не позже чем через 5 с после POST /runs/{rid}/cancel.
    cancel_grace_s: float = 3.0


DEFAULT_TIMING = RunTiming()


class RunParts:
    """Части ответа (9.1) по мере событий прогона и номер последнего события (seq)."""

    def __init__(self) -> None:
        # Any: части — JSON по схемам MessagePart, так они и лежат в chat_messages.parts.
        self.parts: list[dict[str, Any]] = []
        self.seq = 0
        # Пришёл ли текст через run.delta: если нет, бэкенд пришлёт RunResult.text сам.
        self.streamed = False
        # Есть ли изменения, которых ещё нет в базе.
        self.dirty = False

    def delta(self, text: str) -> int:
        """Кусок текста: дописывается в последнюю текстовую часть или начинает новую."""
        if self.parts and self.parts[-1]["type"] == "text":
            self.parts[-1]["text"] += text
        else:
            self.parts.append(_part(TextPart(text=text)))
        self.streamed = True
        return self._next()

    def tool_call(self, call_id: str, tool: str, summary: str) -> int:
        self.parts.append(_part(ToolPart(call_id=call_id, tool=tool, summary=summary)))
        return self._next()

    def tool_result(self, call_id: str, ok: bool, summary: str) -> int:
        """Итог инструмента — в его карточку. Карточки нет — событие всё равно уходит."""
        for part in reversed(self.parts):
            if part["type"] == "tool" and part["call_id"] == call_id and part["ok"] is None:
                part["ok"] = ok
                part["result"] = summary
                break
        else:
            logger.warning("agent_tool_result_without_call", call_id=call_id)
        return self._next()

    def append(self, part: BaseModel) -> None:
        """Часть, которую добавляет сам бэкенд в конце: карточка правок или ошибка."""
        self.parts.append(_part(part))
        self.dirty = True

    def snapshot(self) -> tuple[list[dict[str, Any]], int]:
        """Копия частей и seq для записи в базу; дальше изменения снова копятся."""
        self.dirty = False
        return copy.deepcopy(self.parts), self.seq

    def _next(self) -> int:
        self.seq += 1
        self.dirty = True
        return self.seq


def _part(part: BaseModel) -> dict[str, Any]:
    return part.model_dump(mode="json")


class BackendRunEvents:
    """RunEvents прогона: события с run_id, message_id и seq — в журнал проекта, части —
    в RunParts."""

    def __init__(
        self,
        events: EventPublisher,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        message_id: uuid.UUID,
        parts: RunParts,
    ) -> None:
        self._events = events
        self._project_id = project_id
        self._run_id = run_id
        self._message_id = message_id
        self.parts = parts

    async def delta(self, text: str) -> None:
        # Пустой кусок ничего не меняет, а номер события занял бы.
        if not text:
            return
        seq = self.parts.delta(text)
        data = RunDeltaData(run_id=self._run_id, message_id=self._message_id, seq=seq, text=text)
        await self._events.publish(self._project_id, EventType.RUN_DELTA, data)

    async def tool_call(self, call_id: str, tool: str, summary: str) -> None:
        seq = self.parts.tool_call(call_id, tool, summary)
        data = RunToolCallData(
            run_id=self._run_id, call_id=call_id, seq=seq, tool=tool, summary=summary
        )
        await self._events.publish(self._project_id, EventType.RUN_TOOL_CALL, data)

    async def tool_result(self, call_id: str, ok: bool, summary: str) -> None:
        seq = self.parts.tool_result(call_id, ok, summary)
        data = RunToolResultData(
            run_id=self._run_id, call_id=call_id, seq=seq, ok=ok, summary=summary
        )
        await self._events.publish(self._project_id, EventType.RUN_TOOL_RESULT, data)


@dataclass(frozen=True)
class StartedRun:
    """Прогон, который это задание перевело в running."""

    run_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    changeset_id: uuid.UUID
    message_id: uuid.UUID
    history: Sequence[HistoryMessage]


@dataclass(frozen=True)
class Outcome:
    """Итог прогона для записи: из RunResult, отмены или сбоя."""

    status: RunStatus
    error: str | None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: Decimal = Decimal(0)

    @classmethod
    def of(cls, result: RunResult | None, *, lock_lost: bool) -> "Outcome":
        """Итог по ответу агента. None — агента прервали после отмены. Блокировка проекта
        потеряна — прогон прерван, что бы ни ответил агент: проект уже могли править."""
        if lock_lost:
            status: RunStatus = "failed"
            error: str | None = service.RUN_INTERRUPTED_MESSAGE
        elif result is None:
            status, error = "cancelled", None
        elif result.status == "failed":
            status, error = "failed", result.error or RUN_FAILED_MESSAGE
        else:
            status, error = result.status, None
        if result is None:
            return cls(status=status, error=error)
        usage = result.usage
        return cls(
            status=status,
            error=error,
            model=usage.model,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost=usage.cost,
        )


@dataclass(frozen=True)
class Supervised:
    """Чем кончилось ожидание агента: его ответ (None — прерван после отмены) и не
    потеряна ли блокировка проекта."""

    result: RunResult | None
    lock_lost: bool


async def execute_run(
    run_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    events: EventPublisher,
    templates: Registry,
    run_agent: RunAgent,
    max_tokens: int,
    timing: RunTiming = DEFAULT_TIMING,
) -> None:
    """Выполняет прогон из очереди: блокировка → run.started → агент → итог → run.finished
    → снятие блокировки.

    Задание может прийти повторно: законченный прогон и прогон, чья блокировка жива, не
    трогаются; прогон running с истёкшей блокировкой закрывается как прерванный. Агент
    второй раз не запускается. Исключение из run_agent — failed с общим сообщением,
    подробности только в лог. Воркер останавливают посреди прогона — прерванный прогон.
    """
    started = await _start(sessionmaker, events, run_id)
    if started is None:
        return
    began = time.monotonic()
    project_id = started.project_id
    # Сначала блокировка: редактор станет «только чтение» до первой правки ИИ.
    await events.publish(project_id, EventType.PROJECT_LOCKED, ProjectLockedData(run_id=run_id))
    await events.publish(
        project_id,
        EventType.RUN_STARTED,
        RunStartedData(run_id=run_id, message_id=started.message_id),
    )
    parts = RunParts()
    run_events = BackendRunEvents(events, project_id, run_id, started.message_id, parts)
    context = ToolContext(
        project_id=project_id,
        user_id=started.user_id,
        actor="ai",
        changeset_id=started.changeset_id,
    )
    cancel = asyncio.Event()
    request = RunRequest(
        history=started.history,
        context=context,
        tools=ServiceProjectTools(
            context, sessionmaker=sessionmaker, storage=storage, events=events, templates=templates
        ),
        events=run_events,
        cancel=cancel,
        max_tokens=max_tokens,
    )
    try:
        supervised = await _supervise(
            run_agent(request), sessionmaker, started, parts, cancel, timing
        )
        outcome = Outcome.of(supervised.result, lock_lost=supervised.lock_lost)
        text = supervised.result.text if supervised.result is not None else ""
        # Агент не прислал текст кусками (как заглушка) — он уходит одним run.delta: так
        # чат во время прогона и после перезагрузки выглядит одинаково.
        if not parts.streamed and text:
            await run_events.delta(text)
    except asyncio.CancelledError:
        # Воркер останавливают. Итог записывается, даже если и его попробуют прервать.
        logger.warning("agent_run_interrupted", run_id=str(run_id))
        interrupted = Outcome(status="failed", error=service.RUN_INTERRUPTED_MESSAGE)
        await asyncio.shield(_finish(sessionmaker, events, started, parts, interrupted))
        raise
    except Exception:
        # Без текста истории и ответа: только где упало.
        logger.exception("agent_run_crashed", run_id=str(run_id))
        outcome = Outcome(status="failed", error=RUN_FAILED_MESSAGE)
    await _finish(sessionmaker, events, started, parts, outcome)
    logger.info(
        "agent_run_finished",
        run_id=str(run_id),
        project_id=str(project_id),
        status=outcome.status,
        model=outcome.model,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        duration_ms=round((time.monotonic() - began) * 1000),
    )


async def load_history(
    session: AsyncSession, project_id: uuid.UUID, before_position: int
) -> list[HistoryMessage]:
    """Последние HISTORY_MESSAGES сообщений до before_position и сам запрос — последнее.

    Из ответов берётся только текст: карточки инструментов и ошибки агенту не нужны.
    Сообщения без текста (например, остановленный в очереди прогон) пропускаются, а
    старые длинные сокращаются; запрос пользователя передаётся целиком.
    """
    rows = list(
        await session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.project_id == project_id,
                ChatMessage.position < before_position,
                ChatMessage.role.in_(("user", "assistant")),
            )
            .order_by(ChatMessage.position.desc())
            .limit(HISTORY_MESSAGES + 1)
        )
    )
    messages: list[HistoryMessage] = []
    for index, row in enumerate(reversed(rows)):
        text = message_text(row.parts)
        if not text:
            continue
        if index < len(rows) - 1 and len(text) > HISTORY_MESSAGE_MAX_CHARS:
            text = f"{text[:HISTORY_MESSAGE_MAX_CHARS]}\n{SHORTENED_MARK}"
        role = "user" if row.role == "user" else "assistant"
        messages.append(HistoryMessage(role=role, text=text))
    return messages


def message_text(parts: Sequence[dict[str, Any]]) -> str:
    """Текст сообщения: текстовые части подряд, между карточками — пустая строка."""
    return "\n\n".join(part["text"] for part in parts if part["type"] == "text" and part["text"])


async def _start(
    sessionmaker: async_sessionmaker[AsyncSession], events: EventPublisher, run_id: uuid.UUID
) -> StartedRun | None:
    """Занимает проект и переводит прогон из очереди в running — одной транзакцией, потом
    собирает историю. Нечего начинать — None.

    Блокировка берётся под блокировкой строки проекта: сохранение, которое уже идёт,
    закончится раньше, чем прогон начнётся (history.take_run_lock).
    """
    async with sessionmaker() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.changeset_id is None:
            logger.info("agent_run_skipped", run_id=str(run_id), reason="gone")
            return None
        if run.status == "running":
            # Повторное задание. Блокировка жива — прогон ведёт другой воркер; истекла —
            # воркер упал, и прогон закрывается как прерванный.
            closed = await service.close_dead_runs(session, run_id=run_id)
            await service.publish_closed(events, closed)
            logger.info("agent_run_skipped", run_id=str(run_id), reason="running")
            return None
        if run.status != "queued":
            logger.info("agent_run_skipped", run_id=str(run_id), reason=run.status)
            return None
        project_id, user_id, changeset_id = run.project_id, run.user_id, run.changeset_id
        if not await history.take_run_lock(session, project_id, run_id):
            # Проект держит другой прогон — так быть не должно: прогон у проекта один.
            # Задание отправит снова фоновая проверка, когда блокировка истечёт.
            await session.rollback()
            logger.warning("agent_run_project_busy", run_id=str(run_id))
            return None
        moved = await session.scalar(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status == "queued")
            .values(status="running")
            .returning(AgentRun.id)
        )
        if moved is None:
            # Отменили, пока ждали блокировку строки проекта.
            await session.rollback()
            logger.info("agent_run_skipped", run_id=str(run_id), reason="cancelled")
            return None
        reply = await session.scalar(
            select(ChatMessage).where(ChatMessage.run_id == run_id, ChatMessage.role == "assistant")
        )
        if reply is None:
            raise RuntimeError(f"У прогона {run_id} нет ответа")
        started = StartedRun(
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            changeset_id=changeset_id,
            message_id=reply.id,
            history=await load_history(session, project_id, reply.position),
        )
        await session.commit()
    return started


async def _supervise(
    # Any: так типизированы корутины — send и throw агенту не нужны.
    agent: Coroutine[Any, Any, RunResult],
    sessionmaker: async_sessionmaker[AsyncSession],
    started: StartedRun,
    parts: RunParts,
    cancel: asyncio.Event,
    timing: RunTiming,
) -> Supervised:
    """Ждёт агента. Раз в tick_s сохраняет части ответа и проверяет отмену, раз в renew_s
    продлевает блокировку проекта.

    Студент отменил прогон или блокировка потеряна — взводится cancel. Агент не вернулся
    за cancel_grace_s — воркер прерывает его сам.
    """
    task: asyncio.Task[RunResult] = asyncio.ensure_future(agent)
    lock_lost = False
    deadline: float | None = None
    renewed_at = time.monotonic()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=timing.tick_s)
            if done:
                return Supervised(task.result(), lock_lost)
            renew = time.monotonic() - renewed_at >= timing.renew_s
            tick = await _tick(sessionmaker, started, parts, renew=renew)
            if renew and tick.renewed is not None:
                renewed_at = time.monotonic()
                lock_lost = lock_lost or not tick.renewed
            if (tick.cancel_requested or lock_lost) and deadline is None:
                logger.info(
                    "agent_run_stopping",
                    run_id=str(started.run_id),
                    reason="lock_lost" if lock_lost else "cancel",
                )
                cancel.set()
                deadline = time.monotonic() + timing.cancel_grace_s
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("agent_run_forced_stop", run_id=str(started.run_id))
                return Supervised(None, lock_lost)
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@dataclass(frozen=True)
class Tick:
    """Что узнал присмотр за агентом: просил ли студент отмену и продлилась ли блокировка
    (None — продлевать не пора или база недоступна)."""

    cancel_requested: bool
    renewed: bool | None


async def _tick(
    sessionmaker: async_sessionmaker[AsyncSession],
    started: StartedRun,
    parts: RunParts,
    *,
    renew: bool,
) -> Tick:
    """Сохраняет части ответа, продлевает блокировку и читает отметку отмены — одной
    короткой транзакцией. Сбой базы не останавливает прогон: части запишутся в конце,
    а не продлённая вовремя блокировка истечёт, и следующее продление это покажет."""
    snapshot = parts.snapshot() if parts.dirty else None
    try:
        async with sessionmaker() as session:
            if snapshot is not None:
                saved, seq = snapshot
                await session.execute(
                    update(ChatMessage)
                    .where(ChatMessage.id == started.message_id)
                    .values(parts=saved, seq=seq)
                )
            renewed = None
            if renew:
                renewed = await history.renew_run_lock(session, started.project_id, started.run_id)
            requested = await session.scalar(
                select(AgentRun.cancel_requested_at).where(AgentRun.id == started.run_id)
            )
            await session.commit()
    except Exception:
        if snapshot is not None:
            parts.dirty = True
        logger.warning("agent_run_tick_failed", run_id=str(started.run_id), exc_info=True)
        return Tick(cancel_requested=False, renewed=None)
    return Tick(cancel_requested=requested is not None, renewed=renewed)


async def _finish(
    sessionmaker: async_sessionmaker[AsyncSession],
    events: EventPublisher,
    started: StartedRun,
    parts: RunParts,
    outcome: Outcome,
) -> None:
    """Итог прогона, части ответа и снятие блокировки — одной транзакцией, потом
    run.finished и project.unlocked: вкладка сначала узнаёт итог, потом снова может править.

    Прогон уже не running (его закрыли как прерванный) или удалён с проектом — итог не
    пишется и события не шлются.
    """
    async with sessionmaker() as session:
        if await history.changeset_has_writes(session, started.changeset_id):
            parts.append(ChangesetPart(changeset_id=started.changeset_id))
        if outcome.error is not None:
            parts.append(ErrorPart(text=outcome.error))
        snapshot, seq = parts.snapshot()
        finished = await session.scalar(
            update(AgentRun)
            .where(AgentRun.id == started.run_id, AgentRun.status == "running")
            .values(
                status=outcome.status,
                model=outcome.model,
                tokens_in=outcome.tokens_in,
                tokens_out=outcome.tokens_out,
                cost=outcome.cost,
                error=outcome.error,
                finished_at=func.now(),
            )
            .returning(AgentRun.id)
        )
        if finished is None:
            await session.rollback()
            logger.warning("agent_run_result_dropped", run_id=str(started.run_id))
            return
        await session.execute(
            update(ChatMessage)
            .where(ChatMessage.id == started.message_id)
            .values(parts=snapshot, seq=seq)
        )
        await history.release_run_lock(session, started.project_id, started.run_id)
        await session.commit()
    closed = service.ClosedRun(
        started.project_id, started.run_id, started.changeset_id, outcome.status
    )
    await service.publish_finished(
        events, closed, tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out
    )
    await events.publish(
        started.project_id,
        EventType.PROJECT_UNLOCKED,
        ProjectUnlockedData(run_id=started.run_id),
    )
