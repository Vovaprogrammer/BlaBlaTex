"""Свой ключ LLM студента и расход на ключ сервиса по дням (architecture.md 5)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin


class Usage(Base):
    """Расход студента за день на ключе сервиса: прогоны агента и описания картинок.

    Работа на своём ключе студента сюда не пишется, поэтому строка за сегодня — это и его
    квота, и наши траты. day — дата по Москве (service.QUOTA_TIMEZONE).
    """

    __tablename__ = "usage"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(primary_key=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0), server_default="0")
    # Сколько прогонов агента; описания картинок их не увеличивают.
    runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class LlmKey(CreatedAtMixin, Base):
    """Свой ключ LLM студента (9.1): не больше одного, зашифрован Fernet.

    created_at — когда ключ сохранён: новый ключ заменяет прежний вместе с этой датой.
    """

    __tablename__ = "llm_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Имя из LLM_PROVIDERS, для которого ключ сохранён; сменили основной — ключ не используется.
    provider: Mapped[str] = mapped_column(String(100))
    # Токен Fernet (ASCII). Расшифровывает только service.usable_key.
    encrypted_key: Mapped[str]
    last4: Mapped[str] = mapped_column(String(4))
