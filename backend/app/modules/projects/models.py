"""Проекты (architecture.md 5)."""

import uuid
from typing import get_args

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.modules.projects.schemas import (
    PROJECT_TITLE_MAX_LENGTH,
    TEMPLATE_SLUG_MAX_LENGTH,
    Engine,
    ProjectKind,
)


def _values(literal: object) -> str:
    """Значения Literal для CHECK ... IN (...)."""
    return ", ".join(f"'{value}'" for value in get_args(literal))


class Project(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_values(ProjectKind)})", name="kind"),
        CheckConstraint(f"engine IN ({_values(Engine)})", name="engine"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(PROJECT_TITLE_MAX_LENGTH))
    kind: Mapped[ProjectKind] = mapped_column(String(16))
    template_slug: Mapped[str] = mapped_column(String(TEMPLATE_SLUG_MAX_LENGTH))
    template_version: Mapped[int]
    # Значения полей шаблона, например {"lab_number": 3}.
    fields: Mapped[dict[str, str | int]] = mapped_column(JSONB)
    main_file: Mapped[str] = mapped_column(String(255))
    engine: Mapped[Engine] = mapped_column(String(16))
