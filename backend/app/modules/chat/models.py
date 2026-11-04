"""Чат проекта и прогоны агента (architecture.md 5, 8)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, literal_values
from app.modules.chat.schemas import ActiveRunStatus, RunStatus

# Роль в таблице: system — на будущее (раздел 5), API отдаёт только user и assistant.
ChatRole = Literal["user", "assistant", "system"]

# Имя индекса нужно сервису: по нарушению именно его он отвечает 423, а не 500.
ONE_ACTIVE_RUN_INDEX = "uq_agent_runs_project_id_active"


class AgentRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Прогон агента: queued → running → done | failed | cancelled; итог пишется один раз."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({literal_values(RunStatus)})", name="status"),
        # У проекта не больше одного прогона в очереди или идущего — это держит сама база,
        # сколько бы запросов ни пришло одновременно.
        Index(
            ONE_ACTIVE_RUN_INDEX,
            "project_id",
            unique=True,
            postgresql_where=text(f"status IN ({literal_values(ActiveRunStatus)})"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # Кто отправил сообщение: от его имени пишет агент и на него идёт расход (B3.1).
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[RunStatus] = mapped_column(String(16))
    # Модель и расход — из RunResult.usage; у прогона, который не дошёл до агента, — пусто.
    model: Mapped[str | None] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0), server_default="0")
    # Changeset прогона. Null только внутри транзакции, которая создаёт прогон: changeset
    # ссылается на прогон, поэтому сначала строка прогона, потом changeset.
    changeset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("changesets.id", ondelete="CASCADE")
    )
    # Текст ошибки для пользователя при failed.
    error: Mapped[str | None] = mapped_column(Text)
    # Студент попросил остановить идущий прогон: воркер проверяет это раз в секунду.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Сообщение чата: студента или ответ ассистента (части — как в 9.1)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(f"role IN ({literal_values(ChatRole)})", name="role"),
        # Страница чата: сообщения проекта по порядку.
        Index("ix_chat_messages_project_id_position", "project_id", "position"),
    )

    # Порядок сообщений. Время не годится: сообщение студента и пустой ответ создаются
    # в одной транзакции, и у них может совпасть время.
    position: Mapped[int] = mapped_column(BigInteger, Identity(always=False))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # Прогон, который сообщение начало (студент) или ответ которого оно несёт (ассистент).
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    role: Mapped[ChatRole] = mapped_column(String(16))
    # Any: части — JSON по схемам MessagePart (chat/schemas.py), их проверяет сервис.
    parts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Номер последнего события прогона, которое вошло в parts (9.1, 9.3).
    seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
