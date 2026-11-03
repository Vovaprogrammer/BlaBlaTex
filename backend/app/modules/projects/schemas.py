"""Схемы проектов, дерева файлов и операций с файлами."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, StrictInt, StrictStr
from pydantic_core import PydanticCustomError

from app.core.text import NoNul, reject_nul
from app.modules.projects.paths import MAX_PATH_LENGTH, InvalidPathError, validate_path

ProjectKind = Literal["lab", "vkr", "article", "slides"]
# LuaLaTeX компилятор пока не собирает — причина в architecture.md, раздел 6.
Engine = Literal["xelatex", "pdflatex"]
FileKind = Literal["text", "binary", "folder"]
FileRole = Literal["source", "material", "generated"]


def _fields_without_nul(values: dict[str, str | int]) -> dict[str, str | int]:
    # Проверка всего словаря, а не каждого значения: у ошибки внутри str | int в loc
    # появилась бы метка с именем функции-проверки.
    for key, value in values.items():
        reject_nul(key)
        if isinstance(value, str):
            reject_nul(value)
    return values


# Самое длинное значение поля — у type: text (9.5). Лимит по типу поля модуль шаблонов
# проверяет по манифесту, а схема запроса отсекает огромное значение ещё до сервиса.
FIELD_VALUE_MAX_LENGTH = 10_000


def _value_not_too_long(value: str | int) -> str | int:
    if isinstance(value, str) and len(value) > FIELD_VALUE_MAX_LENGTH:
        raise PydanticCustomError(
            "string_too_long",
            "String should have at most {max_length} characters",
            {"max_length": FIELD_VALUE_MAX_LENGTH},
        )
    return value


# Значения полей шаблона: типы string, text и select — строки, int — число.
# Strict: true и 1.0 не превращаются молча в 1. Длина проверяется у всего str | int:
# с max_length у StrictStr Pydantic дал бы по ошибке на каждый тип и имя типа в loc.
FieldValue = Annotated[StrictStr | StrictInt, AfterValidator(_value_not_too_long)]
FieldValues = Annotated[dict[str, FieldValue], AfterValidator(_fields_without_nul)]
PROJECT_TITLE_MAX_LENGTH = 200
TEMPLATE_SLUG_MAX_LENGTH = 100
ProjectTitle = Annotated[str, Field(min_length=1, max_length=PROJECT_TITLE_MAX_LENGTH), NoNul]


def _valid_path(value: str) -> str:
    try:
        return validate_path(value)
    except InvalidPathError as error:
        # Причина уходит в ответ 422 как текст ошибки поля (core/errors.py).
        raise PydanticCustomError("invalid_path", "{reason}", {"reason": str(error)}) from None


# Путь в теле запроса. Длина в Field — для OpenAPI, все правила 9.8 проверяет validate_path.
ProjectPath = Annotated[
    str, Field(min_length=1, max_length=MAX_PATH_LENGTH), AfterValidator(_valid_path)
]
# Путь из адреса /files/{path}. Без Field: у параметра адреса FastAPI принимает одно описание.
FilePath = Annotated[str, AfterValidator(_valid_path)]


class ProjectCreate(BaseModel):
    title: ProjectTitle
    template_slug: Annotated[str, Field(min_length=1, max_length=TEMPLATE_SLUG_MAX_LENGTH), NoNul]
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
    # Без проверок запроса: у проектов, созданных до лимитов 9.5, значения бывают длиннее.
    fields: dict[str, StrictStr | StrictInt]
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


class UploadResult(BaseModel):
    items: list[FileInfo] = Field(description="Загруженные файлы в порядке запроса")


class FolderCreate(BaseModel):
    path: ProjectPath


class MoveRequest(BaseModel):
    from_: ProjectPath = Field(alias="from")
    to: ProjectPath
