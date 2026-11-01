"""Проекты, дерево и файлы проекта. Шаблоны к проектам подключит A1.2."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response

from app.core.db import DbSession
from app.core.errors import TEXT_CONTENT, request_error
from app.modules.auth.dependencies import SESSION_COOKIE, CurrentUser, unauthorized
from app.modules.projects import service
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.models import File, Project
from app.modules.projects.schemas import (
    FileInfo,
    FilePath,
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


# Версия в ETag и If-Match: число в кавычках. Не больше 18 цифр — влезает в int64.
_ETAG = re.compile(r'"([0-9]{1,18})"')
# В файлах — текст пользователя: браузер не должен угадывать по нему тип
# и открывать, например, page.html как HTML.
_NO_SNIFF = {"X-Content-Type-Options": "nosniff"}


def _project_out(project: Project) -> ProjectOut:
    return ProjectOut.model_validate(project, from_attributes=True)


def _file_info(file: File) -> FileInfo:
    return FileInfo.model_validate(file, from_attributes=True)


def _etag(file: File) -> str:
    return f'"{file.version}"'


def _expected_version(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    match = _ETAG.fullmatch(if_match.strip())
    if match is None:
        raise request_error(["header", "if-match"], 'Ожидается версия в кавычках, например "7"')
    return int(match.group(1))


def _create_only(if_none_match: str | None) -> bool:
    if if_none_match is None:
        return False
    if if_none_match.strip() != "*":
        raise request_error(["header", "if-none-match"], "Поддерживается только значение *")
    return True


async def _read_text(request: Request) -> str:
    """Тело запроса как текст UTF-8. Читается кусками: больше лимита в память не попадёт.

    Без cookie сессии — сразу 401: войти нечем, и дочитывать до 2 МБ незачем. Личные
    токены MCP (B4.1) нужно будет пропускать здесь же.
    """
    if SESSION_COOKIE not in request.cookies:
        raise unauthorized()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > service.TEXT_FILE_MAX_BYTES:
            raise service.file_too_large()
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise request_error(["body"], "Текст должен быть в кодировке UTF-8") from None


# Зависимость, объявленная в маршруте первой, выполняется до входа и поиска проекта:
# пока медленный клиент присылает до 2 МБ, соединение с базой ещё не занято.
TextBody = Annotated[str, Depends(_read_text)]


@router.get("")
async def list_projects(user: CurrentUser, session: DbSession) -> ProjectList:
    """Проекты текущего пользователя, недавно изменённые — первыми."""
    projects = await service.list_projects(session, user.id)
    return ProjectList(items=[_project_out(project) for project in projects])


@router.post("", status_code=201)
async def create_project(body: ProjectCreate, user: CurrentUser, session: DbSession) -> ProjectOut:
    """Создаёт проект с полями шаблона.

    Пока проект создаётся пустым, а поля не проверяются: файлы шаблона и проверку
    по его манифесту добавит модуль шаблонов.
    """
    project = await service.create_project(session, user.id, body)
    return _project_out(project)


@router.get("/{pid}")
async def get_project(project: OwnedProject) -> ProjectOut:
    return _project_out(project)


@router.patch("/{pid}")
async def update_project(
    body: ProjectUpdate, project: OwnedProject, session: DbSession
) -> ProjectOut:
    """Меняет название или поля шаблона; fields заменяются целиком."""
    project = await service.update_project(session, project, body)
    return _project_out(project)


@router.delete("/{pid}", status_code=204)
async def delete_project(project: OwnedProject, session: DbSession) -> None:
    """Удаляет проект со всеми файлами."""
    await service.delete_project(session, project)


@router.get("/{pid}/tree")
async def get_tree(project: OwnedProject, session: DbSession) -> FileTree:
    """Все файлы и папки проекта, по пути."""
    files = await service.list_files(session, project.id)
    return FileTree(items=[_file_info(file) for file in files])


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
async def read_file(project: OwnedProject, path: FilePath, session: DbSession) -> Response:
    """Текст файла в UTF-8; ETag — его версия. Нет файла или это папка — 404."""
    file = await service.read_text_file(session, project.id, path)
    # ETag ставим на сам ответ: заголовки параметра response к возвращённому Response не попадут.
    return Response(
        file.content, media_type="text/plain", headers={"ETag": _etag(file), **_NO_SNIFF}
    )


@router.put(
    "/{pid}/files/{path:path}",
    openapi_extra={"requestBody": {"required": True, "content": TEXT_CONTENT}},
    responses={
        200: {"description": "Файл обновлён", "headers": ETAG_HEADER},
        201: {"model": FileInfo, "description": "Файл создан", "headers": ETAG_HEADER},
    },
)
async def write_file(
    content: TextBody,
    project: OwnedProject,
    path: FilePath,
    response: Response,
    session: DbSession,
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
    Без этих заголовков файл записывается без проверки версии. Тип файла не из 9.8 — 415;
    файл больше 2 МБ или проект больше 200 МБ — 413.
    """
    expected_version = _expected_version(if_match)
    create_only = _create_only(if_none_match)
    file, created = await service.write_text_file(
        session,
        project.id,
        path,
        content,
        expected_version=expected_version,
        create_only=create_only,
    )
    # Возвращаем модель, а не Response, поэтому статус и заголовок из response применятся.
    response.status_code = 201 if created else 200
    response.headers["ETag"] = _etag(file)
    return _file_info(file)


@router.delete("/{pid}/files/{path:path}", status_code=204)
async def delete_file(project: OwnedProject, path: FilePath, session: DbSession) -> None:
    """Удаляет файл или папку со всем содержимым."""
    await service.delete_path(session, project.id, path)


@router.post("/{pid}/folders", status_code=201)
async def create_folder(body: FolderCreate, project: OwnedProject, session: DbSession) -> FileInfo:
    """Создаёт папку; недостающие папки над ней создаются сами. Путь уже занят — 409."""
    folder = await service.create_folder(session, project.id, body.path)
    return _file_info(folder)


@router.post("/{pid}/move")
async def move(body: MoveRequest, project: OwnedProject, session: DbSession) -> FileInfo:
    """Перемещает или переименовывает файл или папку вместе с вложенными.

    Новый путь занят — 409; папку внутрь неё самой — 422; текстовый файл в тип не из 9.8 —
    415. Версии файлов не меняются.
    """
    moved = await service.move_path(session, project.id, body.from_, body.to)
    return _file_info(moved)
