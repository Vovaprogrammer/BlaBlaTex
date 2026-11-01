"""Профиль студента: данные для титульного листа (architecture.md 5)."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from app.core.db import Base, UpdatedAtMixin
from app.modules.profiles.schemas import PROFILE_TEXT_MAX_LENGTH


def _text() -> MappedColumn[str]:
    # Пустая строка — поле ещё не заполнено.
    return mapped_column(String(PROFILE_TEXT_MAX_LENGTH), default="", server_default="")


class Profile(UpdatedAtMixin, Base):
    """Один профиль на пользователя, создаётся пустым при регистрации."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_name: Mapped[str] = _text()
    first_name: Mapped[str] = _text()
    middle_name: Mapped[str] = _text()
    group_name: Mapped[str] = _text()
    faculty: Mapped[str] = _text()
    department: Mapped[str] = _text()
