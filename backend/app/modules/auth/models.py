"""Пользователи и сессии входа (architecture.md 5)."""

import uuid
from datetime import datetime
from typing import get_args

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.modules.auth.schemas import UserRole

_ROLES = ", ".join(f"'{role}'" for role in get_args(UserRole))


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Email хранится в нижнем регистре: так unique не пропустит A@x.ru рядом с a@x.ru.
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint(f"role IN ({_ROLES})", name="role"),
    )

    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role: Mapped[UserRole] = mapped_column(String(16), default="student", server_default="student")
    # Когда пользователь дал согласие на обработку персональных данных.
    consent_at: Mapped[datetime]


class UserSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Сессия браузера. Сам токен живёт только в cookie, здесь — его sha256."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]


class ApiToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Личный токен для агентов через MCP и скриптов (architecture.md 9.1).

    Значение знает только студент, здесь — его sha256. Удалённый токен остаётся строкой
    с revoked_at: по ней агенту отвечают «Токен удалён», а не «Токен не подошёл».
    """

    __tablename__ = "api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Обновляется не чаще раза в час, как last_seen_at у сессии; null — ещё не пользовались.
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
