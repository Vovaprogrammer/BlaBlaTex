"""usage without user

Revision ID: 3b7e1c9d2a41
Revises: 75d9a9b2212b
Create Date: 2026-11-12 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии для Alembic.
revision: str = "3b7e1c9d2a41"
down_revision: str | Sequence[str] | None = "75d9a9b2212b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Строка расхода переживает удаление аккаунта (architecture.md 5): свой id вместо ключа
    # (user_id, day), user_id может быть пустым, уникальность (user_id, day) остаётся.
    op.drop_constraint(op.f("pk_usage"), "usage", type_="primary")
    op.add_column(
        "usage",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    )
    op.create_primary_key(op.f("pk_usage"), "usage", ["id"])
    op.create_unique_constraint(op.f("uq_usage_user_id_day"), "usage", ["user_id", "day"])
    op.alter_column("usage", "user_id", existing_type=sa.Uuid(), nullable=True)
    op.drop_constraint(op.f("fk_usage_user_id_users"), "usage", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_usage_user_id_users"), "usage", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    # Обезличенный расход в прежнюю схему не помещается: у строки нет студента.
    op.execute("DELETE FROM usage WHERE user_id IS NULL")
    op.drop_constraint(op.f("fk_usage_user_id_users"), "usage", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_usage_user_id_users"), "usage", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.alter_column("usage", "user_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint(op.f("uq_usage_user_id_day"), "usage", type_="unique")
    op.drop_constraint(op.f("pk_usage"), "usage", type_="primary")
    op.drop_column("usage", "id")
    op.create_primary_key(op.f("pk_usage"), "usage", ["user_id", "day"])
