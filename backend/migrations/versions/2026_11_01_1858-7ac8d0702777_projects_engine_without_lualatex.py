"""projects engine without lualatex

Revision ID: 7ac8d0702777
Revises: eae924df9b9e
Create Date: 2026-11-01 18:58:54.823154
"""

from collections.abc import Sequence

from alembic import op

# Идентификаторы ревизии для Alembic.
revision: str = "7ac8d0702777"
down_revision: str | Sequence[str] | None = "eae924df9b9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LuaLaTeX компилятор не собирает (architecture.md 6). Выбрать его через API было нельзя,
    # но если такие проекты всё же есть, они переходят на XeLaTeX — движок по умолчанию.
    op.execute("UPDATE projects SET engine = 'xelatex' WHERE engine = 'lualatex'")
    op.drop_constraint(op.f("ck_projects_engine"), "projects", type_="check")
    op.create_check_constraint(
        op.f("ck_projects_engine"), "projects", "engine IN ('xelatex', 'pdflatex')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_projects_engine"), "projects", type_="check")
    op.create_check_constraint(
        op.f("ck_projects_engine"), "projects", "engine IN ('xelatex', 'pdflatex', 'lualatex')"
    )
