"""Текст материала в REST (architecture.md 9.1): что ИИ видит в файле из materials/."""

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.projects.tools import DEFAULT_MATERIAL_LIMIT, MaterialStatus

# Чем получен текст материала (раздел 5).
MaterialMethod = Literal["pdfminer", "markitdown", "text", "image"]

MATERIAL_TEXT_DEFAULT_LIMIT = DEFAULT_MATERIAL_LIMIT
MATERIAL_TEXT_MAX_LIMIT = 100_000


class MaterialTextOut(BaseModel):
    path: str
    status: MaterialStatus = Field(
        description="pending — текст извлекается, ready — готов, failed — не вышло"
    )
    method: MaterialMethod | None = Field(description="Чем получен текст; null, пока не ready")
    pages: int | None = Field(description="Страниц в PDF или слайдов в презентации, иначе null")
    description: str | None = Field(description="Описание картинки или null")
    error: str | None = Field(description="Почему не вышло (failed) — для студента")
    text: str | None = Field(
        description="Не больше limit символов начиная с offset; null, пока не ready"
    )
    offset: int
    total: int = Field(description="Длина всего текста в символах; 0, пока не ready")
