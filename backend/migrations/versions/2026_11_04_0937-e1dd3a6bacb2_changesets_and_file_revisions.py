"""changesets and file revisions

Revision ID: e1dd3a6bacb2
Revises: 9c047b0fdac2
Create Date: 2026-11-04 09:37:09.581275
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии для Alembic.
revision: str = "e1dd3a6bacb2"
down_revision: str | Sequence[str] | None = "9c047b0fdac2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "changesets",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("author", sa.String(length=16), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("reverts_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "author IN ('user', 'ai', 'mcp', 'template', 'system')",
            name=op.f("ck_changesets_author"),
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_changesets_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_changesets_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reverts_id"],
            ["changesets.id"],
            name=op.f("fk_changesets_reverts_id_changesets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_changesets")),
    )
    op.create_index(
        "ix_changesets_project_id_created_at",
        "changesets",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "file_revisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("changeset_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=255, collation="C"), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("blob_sha256", sa.String(length=64), nullable=True),
        sa.Column("mime", sa.String(length=255), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind IS NOT DISTINCT FROM 'binary') = (blob_sha256 IS NOT NULL)",
            name=op.f("ck_file_revisions_binary_blob"),
        ),
        sa.CheckConstraint(
            "(kind IS NOT DISTINCT FROM 'text') = (content IS NOT NULL)",
            name=op.f("ck_file_revisions_text_content"),
        ),
        sa.CheckConstraint(
            "kind IN ('text', 'binary', 'folder')", name=op.f("ck_file_revisions_kind")
        ),
        sa.CheckConstraint(
            "(path IS NULL) = (kind IS NULL)", name=op.f("ck_file_revisions_existed")
        ),
        sa.ForeignKeyConstraint(
            ["changeset_id"],
            ["changesets.id"],
            name=op.f("fk_file_revisions_changeset_id_changesets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_revisions")),
    )
    op.create_index(
        op.f("ix_file_revisions_changeset_id"), "file_revisions", ["changeset_id"], unique=False
    )
    op.create_index(
        "ix_file_revisions_file_id_id", "file_revisions", ["file_id", "id"], unique=False
    )
    op.add_column(
        "projects", sa.Column("last_file_version", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("projects", sa.Column("last_changeset_id", sa.Uuid(), nullable=True))
    # Версии сквозные (раздел 5): счётчик продолжает самую большую версию файлов проекта,
    # и номера уже открытых во вкладках файлов остаются верными. Истории у старых файлов
    # нет — она начнётся с первой правки, и та сохранит прежний вид файла.
    op.execute(
        "UPDATE projects SET last_file_version = "
        "(SELECT coalesce(max(version), 0) FROM files WHERE files.project_id = projects.id)"
    )


def downgrade() -> None:
    op.drop_column("projects", "last_changeset_id")
    op.drop_column("projects", "last_file_version")
    op.drop_index("ix_file_revisions_file_id_id", table_name="file_revisions")
    op.drop_index(op.f("ix_file_revisions_changeset_id"), table_name="file_revisions")
    op.drop_table("file_revisions")
    op.drop_index("ix_changesets_project_id_created_at", table_name="changesets")
    op.drop_table("changesets")
