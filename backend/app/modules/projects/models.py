"""Проекты, их файлы и история правок (architecture.md 5)."""

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
    literal_values,
)
from app.core.events import Author
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
    # Последний выданный номер версии файла: версии сквозные в пределах проекта (раздел 5).
    last_file_version: Mapped[int] = mapped_column(default=0, server_default="0")
    # Changeset последней записи — к нему склеиваются автосохранения. Без внешнего ключа:
    # проект и его changesets ссылались бы друг на друга, и удаление проекта шло бы по кругу.
    last_changeset_id: Mapped[uuid.UUID | None]


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
    # Номер последней записи содержимого — сквозной в проекте (Project.last_file_version);
    # по нему работают ETag и If-Match. У папок не меняется.
    version: Mapped[int] = mapped_column(default=1, server_default="1")


class Changeset(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Группа правок одного автора: её показывают в истории и откатывают целиком."""

    __tablename__ = "changesets"
    __table_args__ = (
        CheckConstraint(f"author IN ({literal_values(Author)})", name="author"),
        Index("ix_changesets_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    author: Mapped[Author] = mapped_column(String(16))
    # От чьего имени правки; null — не от имени пользователя.
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    message: Mapped[str | None] = mapped_column(Text)
    # Прогон ИИ, чей это changeset. use_alter: прогон тоже ссылается на свой changeset.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL", use_alter=True)
    )
    # Откат: какой changeset он откатывает.
    reverts_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("changesets.id", ondelete="SET NULL")
    )
    # updated_at — время последней записи в changeset.


class FileRevision(CreatedAtMixin, Base):
    """Каким был файл или папка до того, как changeset их изменил.

    path и kind — null: файла до changeset не было. Каким файл стал после — следующая
    ревизия этого файла или сам файл сейчас. id растёт по порядку записи: правки проекта
    идут под блокировкой его строки, поэтому порядок id — порядок правок.
    """

    __tablename__ = "file_revisions"
    __table_args__ = (
        CheckConstraint(f"kind IN ({literal_values(FileKind)})", name="kind"),
        CheckConstraint("(path IS NULL) = (kind IS NULL)", name="existed"),
        CheckConstraint(
            "(kind IS NOT DISTINCT FROM 'text') = (content IS NOT NULL)", name="text_content"
        ),
        CheckConstraint(
            "(kind IS NOT DISTINCT FROM 'binary') = (blob_sha256 IS NOT NULL)", name="binary_blob"
        ),
        Index("ix_file_revisions_file_id_id", "file_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    changeset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("changesets.id", ondelete="CASCADE"), index=True
    )
    # Без внешнего ключа: файл удаляют, а его ревизии остаются. Откат удаления создаёт
    # файл снова с тем же id — история файла не рвётся.
    file_id: Mapped[uuid.UUID]
    path: Mapped[str | None] = mapped_column(String(MAX_PATH_LENGTH, collation="C"))
    kind: Mapped[FileKind | None] = mapped_column(String(16))
    content: Mapped[str | None] = mapped_column(Text)
    blob_sha256: Mapped[str | None] = mapped_column(String(64))
    mime: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[int | None] = mapped_column(BigInteger)
