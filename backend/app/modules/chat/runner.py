"""Прогон агента в воркере (architecture.md 8, 9.3, 9.4).

Задание прогона берёт прогон из очереди, собирает историю чата, вызывает run_agent с
настоящими ProjectTools и записывает итог: статус и расход в agent_runs, части ответа
в сообщение ассистента. События run.started и run.finished шлёт сам; run.delta,
run.tool_call и run.tool_result шлёт агент через RunEvents, а бэкенд добавляет к ним
run_id, message_id и номер seq и складывает их в части ответа.
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
    RunDeltaData,
    RunFinishedData,
    RunStartedData,
    RunToolCallData,
    RunToolResultData,
    RunUsage,
)
from app.core.storage import Storage
from app.modules.agent.contract import HistoryMessage, RunAgent, RunRequest, RunResult, RunStatus
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
# Как часто части ответа сохраняются в базу во время прогона: вкладка, открытая посреди
# прогона, получит их из GET /messages.
FLUSH_INTERVAL_S = 1.0
RUN_FAILED_MESSAGE = "Не удалось выполнить запрос. Попробуйте ещё раз."


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
    """Итог прогона для записи: из RunResult или из сбоя."""

    status: RunStatus
    error: str | None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: Decimal = Decimal(0)

    @classmethod
    def of(cls, result: RunResult) -> "Outcome":
        usage = result.usage
        error = (result.error or RUN_FAILED_MESSAGE) if result.status == "failed" else None
        return cls(
            status=result.status,
            error=error,
            model=usage.model,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost=usage.cost,
        )


async def execute_run(
    run_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    events: EventPublisher,
    templates: Registry,
    run_agent: RunAgent,
    max_tokens: int,
    flush_interval_s: float = FLUSH_INTERVAL_S,
) -> None:
    """Выполняет прогон из очереди: run.started → агент → итог → run.finished.

    Задание может прийти повторно: прогон, который уже не в очереди, не трогается, и агент
    второй раз не запускается. Исключение из run_agent — failed с общим сообщением,
    подробности только в лог.
    """
    started = await _start(sessionmaker, run_id)
    if started is None:
        return
    began = time.monotonic()
    await events.publish(
        started.project_id,
        EventType.RUN_STARTED,
        RunStartedData(run_id=run_id, message_id=started.message_id),
    )
    parts = RunParts()
    run_events = BackendRunEvents(events, started.project_id, run_id, started.message_id, parts)
    context = ToolContext(
        project_id=started.project_id,
        user_id=started.user_id,
        actor="ai",
        changeset_id=started.changeset_id,
    )
    request = RunRequest(
        history=started.history,
        context=context,
        tools=ServiceProjectTools(
            context, sessionmaker=sessionmaker, storage=storage, events=events, templates=templates
        ),
        events=run_events,
        cancel=asyncio.Event(),
        max_tokens=max_tokens,
    )
    try:
        result = await _supervise(
            run_agent(request), sessionmaker, started, parts, flush_interval_s
        )
        outcome = Outcome.of(result)
        # Агент не прислал текст кусками (как заглушка) — он уходит одним run.delta: так
        # чат во время прогона и после перезагрузки выглядит одинаково.
        if not parts.streamed and result.text:
            await run_events.delta(result.text)
    except Exception:
        # Без текста истории и ответа: только где упало.
        logger.exception("agent_run_crashed", run_id=str(run_id))
        outcome = Outcome(status="failed", error=RUN_FAILED_MESSAGE)
    await _finish(sessionmaker, events, started, parts, outcome)
    logger.info(
        "agent_run_finished",
        run_id=str(run_id),
        project_id=str(started.project_id),
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
    sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID
) -> StartedRun | None:
    """Переводит прогон из очереди в running и собирает историю. Прогон уже начат, закончен
    или удалён вместе с проектом — None."""
    async with sessionmaker() as session:
        run = await session.scalar(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status == "queued")
            .values(status="running")
            .returning(AgentRun)
        )
        if run is None or run.changeset_id is None:
            await session.rollback()
            logger.info("agent_run_skipped", run_id=str(run_id))
            return None
        reply = await session.scalar(
            select(ChatMessage).where(ChatMessage.run_id == run_id, ChatMessage.role == "assistant")
        )
        if reply is None:
            raise RuntimeError(f"У прогона {run_id} нет ответа")
        started = StartedRun(
            run_id=run_id,
            project_id=run.project_id,
            user_id=run.user_id,
            changeset_id=run.changeset_id,
            message_id=reply.id,
            history=await load_history(session, run.project_id, reply.position),
        )
        await session.commit()
    return started


async def _supervise(
    # Any: так типизированы корутины — send и throw агенту не нужны.
    agent: Coroutine[Any, Any, RunResult],
    sessionmaker: async_sessionmaker[AsyncSession],
    started: StartedRun,
    parts: RunParts,
    flush_interval_s: float,
) -> RunResult:
    """Ждёт агента и раз в flush_interval_s сохраняет части ответа."""
    task: asyncio.Task[RunResult] = asyncio.ensure_future(agent)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=flush_interval_s)
            if done:
                return task.result()
            if parts.dirty:
                await _flush(sessionmaker, started, parts)
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def _flush(
    sessionmaker: async_sessionmaker[AsyncSession], started: StartedRun, parts: RunParts
) -> None:
    """Сохраняет части ответа посреди прогона. Сбой не останавливает прогон: в конце они
    запишутся ещё раз."""
    snapshot, seq = parts.snapshot()
    try:
        async with sessionmaker() as session:
            await session.execute(
                update(ChatMessage)
                .where(ChatMessage.id == started.message_id)
                .values(parts=snapshot, seq=seq)
            )
            await session.commit()
    except Exception:
        parts.dirty = True
        logger.warning("agent_parts_flush_failed", run_id=str(started.run_id), exc_info=True)


async def _finish(
    sessionmaker: async_sessionmaker[AsyncSession],
    events: EventPublisher,
    started: StartedRun,
    parts: RunParts,
    outcome: Outcome,
) -> None:
    """Итог прогона и части ответа — одной транзакцией, потом run.finished.

    Прогон уже не running (его закрыли как прерванный) или удалён с проектом — итог не
    пишется и событие не шлётся.
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
        await session.commit()
    await events.publish(
        started.project_id,
        EventType.RUN_FINISHED,
        RunFinishedData(
            run_id=started.run_id,
            status=outcome.status,
            changeset_id=started.changeset_id,
            usage=RunUsage(tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out),
        ),
    )
