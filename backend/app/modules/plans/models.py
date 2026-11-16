"""План отчёта проекта (architecture.md 5 «План отчёта»)."""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, literal_values
from app.modules.plans.schemas import PlanStatus


class ReportPlanRow(CreatedAtMixin, UpdatedAtMixin, Base):
    """План отчёта: у проекта не больше одного, новый заменяет прежний.

    В plan — только разделы {section_id, materials, note}: названия, порядок и материалы
    вне плана считаются при чтении по шаблону и текущим материалам (service.build_plan).
    """

    __tablename__ = "report_plans"
    __table_args__ = (CheckConstraint(f"status IN ({literal_values(PlanStatus)})", name="status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    # Any: JSON {"sections": [StoredSection]} — его пишет и читает только service.py.
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[PlanStatus] = mapped_column(String(16))
