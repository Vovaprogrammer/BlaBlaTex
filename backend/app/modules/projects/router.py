"""Проекты, дерево и файлы проекта. Пока заглушки: логику добавят B1.3 и A1.2."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response

from app.core.errors import TEXT_CONTENT, not_implemented
from app.modules.projects.schemas import (
    FileInfo,
    FileTree,
    FolderCreate,
    MoveRequest,
    ProjectCreate,
    ProjectList,
    ProjectOut,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])

ETAG_HEADER = {
    "ETag": {
        "description": 'Версия файла в кавычках, например "7"',
        "schema": {"type": "string"},
    }
}


@router.get("")
async def list_projects() -> ProjectList:
    """Проекты текущего пользователя."""
    raise not_implemented()


@router.post("", status_code=201)
async def create_project(body: ProjectCreate) -> ProjectOut:
    """Создаёт проект из шаблона; поля проверяются по манифесту шаблона."""
    raise not_implemented()


@router.get("/{pid}")
async def get_project(pid: UUID) -> ProjectOut:
    raise not_implemented()


@router.patch("/{pid}")
async def update_project(pid: UUID, body: ProjectUpdate) -> ProjectOut:
    """Меняет название или поля шаблона; при новых полях пересоздаётся meta.tex."""
    raise not_implemented()


@router.delete("/{pid}", status_code=204)
async def delete_project(pid: UUID) -> None:
    raise not_implemented()


@router.get("/{pid}/tree")
async def get_tree(pid: UUID) -> FileTree:
    """Все файлы и папки проекта."""
    raise not_implemented()


@router.get(
    "/{pid}/files/{path:path}",
    response_class=Response,
    responses={
        200: {
            "description": "Содержимое файла как есть",
            "headers": ETAG_HEADER,
            "content": TEXT_CONTENT,
        }
    },
)
async def read_file(pid: UUID, path: str) -> Response:
    raise not_implemented()


@router.put(
    "/{pid}/files/{path:path}",
    openapi_extra={"requestBody": {"required": True, "content": TEXT_CONTENT}},
    responses={
        200: {"description": "Файл обновлён", "headers": ETAG_HEADER},
        201: {"model": FileInfo, "description": "Файл создан", "headers": ETAG_HEADER},
    },
)
async def write_file(
    pid: UUID,
    path: str,
    request: Request,
    if_match: Annotated[
        str | None, Header(description='Версия, которую правили, например "7"')
    ] = None,
    if_none_match: Annotated[
        str | None, Header(description="* — создать файл, только если его ещё нет")
    ] = None,
) -> FileInfo:
    """Записывает текст файла; тело запроса — сам текст в UTF-8.

    Промежуточные папки создаются сами. Версия не совпала с If-Match — 412 file_conflict
    с current_version; файл уже есть при If-None-Match: * — 409 already_exists.
    """
    raise not_implemented()


@router.delete("/{pid}/files/{path:path}", status_code=204)
async def delete_file(pid: UUID, path: str) -> None:
    """Удаляет файл или папку со всем содержимым."""
    raise not_implemented()


@router.post("/{pid}/folders", status_code=201)
async def create_folder(pid: UUID, body: FolderCreate) -> FileInfo:
    raise not_implemented()


@router.post("/{pid}/move")
async def move(pid: UUID, body: MoveRequest) -> FileInfo:
    """Перемещает или переименовывает файл или папку вместе с вложенными."""
    raise not_implemented()
