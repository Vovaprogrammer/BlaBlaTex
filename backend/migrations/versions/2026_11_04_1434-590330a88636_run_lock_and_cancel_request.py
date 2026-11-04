"""run lock and cancel request

Revision ID: 590330a88636
Revises: db09d0ed3def
Create Date: 2026-11-04 14:34:21.313633
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии для Alembic.
revision: str = "590330a88636"
down_revision: str | Sequence[str] | None = "db09d0ed3def"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("projects", sa.Column("run_lock_id", sa.Uuid(), nullable=True))
    op.add_column(
        "projects", sa.Column("run_lock_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("projects", "run_lock_until")
    op.drop_column("projects", "run_lock_id")
    op.drop_column("agent_runs", "cancel_requested_at")
