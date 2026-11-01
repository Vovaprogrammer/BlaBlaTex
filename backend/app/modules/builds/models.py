"""Сборки проектов (architecture.md 5). Файлы сборки лежат в Storage, здесь — их sha256."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, literal_values
from app.modules.builds.schemas import BuildStatus
from app.modules.projects.schemas import Engine

SHA256_LENGTH = 64


class Build(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Одна сборка проекта. Строка не меняется после записи: новая сборка — новая строка."""

    __tablename__ = "builds"
    __table_args__ = (
        CheckConstraint(f"status IN ({literal_values(BuildStatus)})", name="status"),
        CheckConstraint(f"engine IN ({literal_values(Engine)})", name="engine"),
        # Последняя сборка проекта.
        Index("ix_builds_project_id_created_at", "project_id", "created_at"),
        # Кэш: успешная сборка проекта с теми же входными данными.
        Index("ix_builds_project_id_inputs_hash", "project_id", "inputs_hash"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[BuildStatus] = mapped_column(String(16))
    engine: Mapped[Engine] = mapped_column(String(16))
    # Ключ кэша (architecture.md 6). null — до компилятора дело не дошло: например,
    # в проекте нет главного файла.
    inputs_hash: Mapped[str | None] = mapped_column(String(SHA256_LENGTH))
    pdf_sha256: Mapped[str | None] = mapped_column(String(SHA256_LENGTH))
    log_sha256: Mapped[str | None] = mapped_column(String(SHA256_LENGTH))
    synctex_sha256: Mapped[str | None] = mapped_column(String(SHA256_LENGTH))
    # Ошибки и предупреждения из лога — список BuildError (builds/schemas.py) в JSON.
    errors: Mapped[list[dict[str, str | int | None]]] = mapped_column(JSONB, default=list)
    pages: Mapped[int | None]
    duration_ms: Mapped[int | None]
