"""Извлечённый текст материалов (architecture.md 5)."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, literal_values
from app.modules.projects.tools import MaterialStatus


class MaterialText(UpdatedAtMixin, Base):
    """Итог извлечения текста одного материала — файла role=material (B2.7).

    Строка есть у каждого материала с момента, когда он появился в materials/, и удаляется
    вместе с файлом. pending — текст ещё извлекается, ready — готов, failed — не вышло.
    """

    __tablename__ = "material_text"
    __table_args__ = (
        CheckConstraint(f"status IN ({literal_values(MaterialStatus)})", name="status"),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[MaterialStatus] = mapped_column(
        String(16), default="pending", server_default="pending"
    )
    # Текст для ИИ: извлечённый из документа или сам код.
    text: Mapped[str | None] = mapped_column(Text)
    # Чем извлечён текст, например markitdown.
    method: Mapped[str | None] = mapped_column(String(32))
    pages: Mapped[int | None]
    # Описание картинки от vision-модели (A2.4).
    description: Mapped[str | None] = mapped_column(Text)
    # Почему не вышло (status=failed) — для пользователя, на русском.
    error: Mapped[str | None] = mapped_column(Text)
