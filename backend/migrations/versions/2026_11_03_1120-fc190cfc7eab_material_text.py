"""material_text

Revision ID: fc190cfc7eab
Revises: b86482d398d6
Create Date: 2026-11-03 11:20:08.643568
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии для Alembic.
revision: str = "fc190cfc7eab"
down_revision: str | Sequence[str] | None = "b86482d398d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "material_text",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name=op.f("ck_material_text_status")
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_material_text_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("file_id", name=op.f("pk_material_text")),
    )
    # Файлы, созданные до правила «роль задаёт путь» (9.8): например, текст, записанный
    # в materials/ через PUT, был source, а перенесённый оттуда материал оставался material.
    op.execute(
        "UPDATE files SET role = 'material' "
        "WHERE role = 'source' AND kind <> 'folder' AND path LIKE 'materials/%'"
    )
    op.execute(
        "UPDATE files SET role = 'source' WHERE role = 'material' AND path NOT LIKE 'materials/%'"
    )
    # У каждого материала — строка (раздел 5): текст из них ещё не извлекался.
    op.execute(
        "INSERT INTO material_text (file_id) "
        "SELECT id FROM files WHERE role = 'material' AND kind <> 'folder'"
    )


def downgrade() -> None:
    op.drop_table("material_text")
