"""Проекты и их файлы (architecture.md 5)."""

import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
    literal_values,
)
from app.modules.projects.paths import MAX_PATH_LENGTH
from app.modules.projects.schemas import (
    PROJECT_TITLE_MAX_LENGTH,
    TEMPLATE_SLUG_MAX_LENGTH,
    Engine,
    FileKind,
    FileRole,
    ProjectKind,
)


class Project(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"kind IN ({literal_values(ProjectKind)})", name="kind"),
        CheckConstraint(f"engine IN ({literal_values(Engine)})", name="engine"),
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


class File(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    """Файл или папка проекта. Дерево — по путям: папка — отдельная строка с kind=folder."""

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("project_id", "path"),
        CheckConstraint(f"kind IN ({literal_values(FileKind)})", name="kind"),
        CheckConstraint(f"role IN ({literal_values(FileRole)})", name="role"),
        # Текст лежит в content, бинарный файл — в Storage по blob_sha256, у папки нет ничего.
        CheckConstraint("(kind = 'text') = (content IS NOT NULL)", name="text_content"),
        CheckConstraint("(kind = 'binary') = (blob_sha256 IS NOT NULL)", name="binary_blob"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # Сравнение и сортировка путей — побайтово (collation C), а не по правилам языка:
    # так дерево упорядочено предсказуемо, а поиск по префиксу папки идёт по индексу.
    path: Mapped[str] = mapped_column(String(MAX_PATH_LENGTH, collation="C"))
    kind: Mapped[FileKind] = mapped_column(String(16))
    role: Mapped[FileRole] = mapped_column(String(16))
    content: Mapped[str | None] = mapped_column(Text)
    blob_sha256: Mapped[str | None] = mapped_column(String(64))
    mime: Mapped[str | None] = mapped_column(String(255))
    # Размер в байтах; у папки — 0.
    size: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # Растёт с каждой записью содержимого; по ней работают ETag и If-Match.
    version: Mapped[int] = mapped_column(default=1, server_default="1")
