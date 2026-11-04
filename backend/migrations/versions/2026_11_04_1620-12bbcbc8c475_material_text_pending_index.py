"""material text pending index

Revision ID: 12bbcbc8c475
Revises: 590330a88636
Create Date: 2026-11-04 16:20:36.681293
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии для Alembic.
revision: str = "12bbcbc8c475"
down_revision: str | Sequence[str] | None = "590330a88636"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_material_text_pending_updated_at",
        "material_text",
        ["updated_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_material_text_pending_updated_at",
        table_name="material_text",
        postgresql_where=sa.text("status = 'pending'"),
    )
