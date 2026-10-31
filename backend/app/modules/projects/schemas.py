"""Схемы проектов, дерева файлов и операций с файлами."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictInt, StrictStr

ProjectKind = Literal["lab", "vkr", "article", "slides"]
Engine = Literal["xelatex", "pdflatex", "lualatex"]
FileKind = Literal["text", "binary", "folder"]
FileRole = Literal["source", "material", "generated"]

# Значения полей шаблона: типы string, text и select — строки, int — число.
# Strict: true и 1.0 не превращаются молча в 1.
FieldValues = dict[str, StrictStr | StrictInt]
ProjectTitle = Annotated[str, Field(min_length=1, max_length=200)]
# Длина — по 9.8; остальные правила путей проверяет сервис файлов.
ProjectPath = Annotated[str, Field(min_length=1, max_length=255)]


class ProjectCreate(BaseModel):
    title: ProjectTitle
    template_slug: str
    fields: FieldValues


class ProjectUpdate(BaseModel):
    """PATCH: передаются только поля, которые меняются."""

    title: ProjectTitle | None = None
    fields: FieldValues | None = None


class ProjectOut(BaseModel):
    id: UUID
    title: str
    kind: ProjectKind
    template_slug: str
    template_version: int
    fields: FieldValues
    main_file: str
    engine: Engine
    created_at: datetime
    updated_at: datetime


class ProjectList(BaseModel):
    items: list[ProjectOut]


class FileInfo(BaseModel):
    path: str
    kind: FileKind
    role: FileRole
    mime: str | None
    size: int = Field(description="Размер в байтах; у папки — 0")
    version: int
    updated_at: datetime


class FileTree(BaseModel):
    items: list[FileInfo]


class FolderCreate(BaseModel):
    path: ProjectPath


class MoveRequest(BaseModel):
    from_: ProjectPath = Field(alias="from")
    to: ProjectPath
