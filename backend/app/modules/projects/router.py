"""Проекты, дерево и файлы проекта. Проект создаётся из шаблона через модуль шаблонов."""

import re
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.db import DbSession
from app.core.errors import TEXT_CONTENT, AppError, ErrorCode, request_error
from app.core.storage import StorageDep
from app.modules.auth.dependencies import SESSION_COOKIE, CurrentUser, unauthorized
from app.modules.projects import service
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.models import File, Project
from app.modules.projects.paths import BINARY_FILE_TYPES
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
    UploadResult,
)
from app.modules.templates import service as templates_service
from app.modules.templates.dependencies import Templates

router = APIRouter(prefix="/projects", tags=["projects"])

ETAG_HEADER = {
    "ETag": {
        "description": 'Версия файла в кавычках, например "7"',
        "schema": {"type": "string"},
    }
}
DOWNLOAD_HEADERS = {
    **ETAG_HEADER,
    "Content-Disposition": {
        "description": "inline и имя файла; русское имя — в filename* (UTF-8)",
        "schema": {"type": "string"},
    },
}
# Ответ GET файла: текст или один из бинарных типов 9.8.
FILE_CONTENT = {
    **TEXT_CONTENT,
    **{
        mime: {"schema": {"type": "string", "format": "binary"}}
        for mime in sorted(set(BINARY_FILE_TYPES.values()))
    },
}
# Тело загрузки описано вручную: форму разбирает сам маршрут, с лимитами 9.8, а не FastAPI.
UPLOAD_BODY = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["files"],
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "contentMediaType": "application/octet-stream",
                        },
                        "description": "Файлы: поле повторяется для каждого файла",
                    },
                    "dir": {
                        "type": "string",
                        "default": "",
                        "description": "Папка назначения; пусто — корень проекта",
                    },
                },
            }
        }
    },
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


def _content_disposition(path: str) -> str:
    """inline и имя файла для «Сохранить как». Русское имя — в filename* (RFC 6266),
    а в filename — для старых клиентов — то же имя с _ вместо символов не из ASCII.
    Кавычек и \\ в имени нет — их запрещает validate_path (9.8)."""
    name = PurePosixPath(path).name
    fallback = "".join(char if char.isascii() and char.isprintable() else "_" for char in name)
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


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


class _UploadParser(MultiPartParser):
    """Разбор multipart из Starlette, но в памяти — только первые 64 КБ каждого файла,
    остальное сразу во временный файл на диске (у Starlette — до 1 МБ на файл)."""

    spool_max_size = 64 * 1024


@dataclass(frozen=True)
class UploadForm:
    folder: str
    files: list[service.IncomingFile]


def _upload_too_large() -> AppError:
    return AppError(
        ErrorCode.PAYLOAD_TOO_LARGE,
        f"За один раз можно загрузить до {service.PROJECT_MAX_BYTES // service.MB} МБ",
        413,
    )


async def _limited(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Тело запроса, которое обрывается, как только пришло больше лимита загрузки."""
    received = 0
    async with aclosing(stream):
        async for chunk in stream:
            received += len(chunk)
            if received > service.UPLOAD_REQUEST_MAX_BYTES:
                raise _upload_too_large()
            yield chunk


async def _read_upload(request: Request) -> AsyncIterator[UploadForm]:
    """Форма загрузки: файлы во временных файлах и папка назначения.

    Разбирается здесь, а не FastAPI: он читает форму до любой проверки и без лимита
    размера. Без cookie сессии — сразу 401, как у PUT. Временные файлы закрываются
    (и удаляются) после ответа.
    """
    if SESSION_COOKIE not in request.cookies:
        raise unauthorized()
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise service.upload_error(
            ["header", "content-type"], "Файлы отправляются как multipart/form-data"
        )
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > service.UPLOAD_REQUEST_MAX_BYTES:
        raise _upload_too_large()
    # aclosing: если разбор оборвётся раньше конца тела, поток запроса закроется сразу.
    async with aclosing(_limited(request.stream())) as body:
        parser = _UploadParser(
            request.headers,
            body,
            max_files=service.UPLOAD_MAX_FILES,
            max_fields=10,
            max_part_size=4096,
        )
        try:
            form = await parser.parse()
        except MultiPartException as error:
            # У Starlette текст ошибки — единственный признак, что превышен лимит файлов.
            message = (
                f"За один раз можно загрузить не больше {service.UPLOAD_MAX_FILES} файлов"
                if error.message.startswith("Too many files")
                else "Не удалось прочитать файлы из запроса"
            )
            raise service.upload_error(["body"], message) from None
    try:
        # Файлы под другим именем поля (например, files[]) молча не потеряются.
        for key, value in form.multi_items():
            if key != "files" and isinstance(value, UploadFile):
                raise service.upload_error(["body", key], "Файлы передаются в поле files")
        files: list[service.IncomingFile] = []
        for index, item in enumerate(form.getlist("files")):
            if not isinstance(item, UploadFile):
                raise service.upload_error(["body", "files", index], "Ожидается файл")
            files.append(service.IncomingFile(item.filename or "", item.file, item.size or 0))
        folder = form.get("dir", "")
        if not isinstance(folder, str):
            raise service.upload_error(["body", "dir"], "Ожидается путь папки")
        yield UploadForm(folder, files)
    finally:
        await form.close()


# Как TextBody: объявляется в маршруте первым, база не занята, пока приходят файлы.
UploadBody = Annotated[UploadForm, Depends(_read_upload)]


@router.get("")
async def list_projects(user: CurrentUser, session: DbSession) -> ProjectList:
    """Проекты текущего пользователя, недавно изменённые — первыми."""
    projects = await service.list_projects(session, user.id)
    return ProjectList(items=[_project_out(project) for project in projects])


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate, user: CurrentUser, session: DbSession, templates: Templates
) -> ProjectOut:
    """Создаёт проект из шаблона: с его файлами, kind, движком и главным файлом.

    Поля проверяются по шаблону: неизвестное, пропущенное обязательное или неверное
    значение — 422 с ключом поля в loc; непереданное поле с default получает default.
    Нет такого шаблона — 422 у template_slug.
    """
    project = await templates_service.create_project(session, user.id, body, templates)
    return _project_out(project)


@router.get("/{pid}")
async def get_project(project: OwnedProject) -> ProjectOut:
    return _project_out(project)


@router.patch("/{pid}")
async def update_project(
    body: ProjectUpdate, project: OwnedProject, session: DbSession, templates: Templates
) -> ProjectOut:
    """Меняет название или поля шаблона; fields заменяются целиком и проверяются по шаблону."""
    project = await templates_service.update_project(session, project, body, templates)
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
            "headers": DOWNLOAD_HEADERS,
            "content": FILE_CONTENT,
        }
    },
)
async def read_file(
    project: OwnedProject, path: FilePath, session: DbSession, storage: StorageDep
) -> Response:
    """Файл как есть; ETag — его версия. Нет файла или это папка — 404.

    Текстовый — в UTF-8, бинарный — потоком с типом, определённым при загрузке;
    у SVG ещё Content-Security-Policy: sandbox.
    """
    file = await service.read_file(session, project.id, path)
    # Заголовки ставим на сам ответ: заголовки параметра response к возвращённому Response
    # не попадут.
    headers = {
        "ETag": _etag(file),
        "Content-Disposition": _content_disposition(file.path),
        **_NO_SNIFF,
    }
    if file.kind == "text":
        return Response(file.content, media_type="text/plain", headers=headers)
    # Скрипт внутри SVG не выполнится, даже если открыть картинку по прямой ссылке.
    # PDF так не закрыть: встроенный просмотрщик Chrome с этим заголовком его не показывает.
    if file.mime == "image/svg+xml":
        headers["Content-Security-Policy"] = "sandbox"
    stream = await service.open_binary(storage, file)
    headers["Content-Length"] = str(file.size)
    return StreamingResponse(stream, media_type=file.mime, headers=headers)


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
    файл больше 2 МБ или проект больше 200 МБ — 413. Сгенерированный файл (role=generated,
    например meta.tex) — 403, даже с If-Match или If-None-Match. Новый файл в materials/ —
    материал (role=material).
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
    """Удаляет файл или папку со всем содержимым.

    Сгенерированный файл (role=generated, например meta.tex) и папку с ним — 403.
    """
    await service.delete_path(session, project.id, path)


@router.post("/{pid}/folders", status_code=201)
async def create_folder(body: FolderCreate, project: OwnedProject, session: DbSession) -> FileInfo:
    """Создаёт папку; недостающие папки над ней создаются сами. Путь уже занят — 409."""
    folder = await service.create_folder(session, project.id, body.path)
    return _file_info(folder)


@router.post("/{pid}/upload", openapi_extra={"requestBody": UPLOAD_BODY})
async def upload(
    form: UploadBody, project: OwnedProject, session: DbSession, storage: StorageDep
) -> UploadResult:
    """Загружает файлы в папку dir; в materials/ они становятся материалами.

    Всё или ничего: не подошёл один файл — не сохраняется ни один, ошибка называет его
    (details.path). Файл по этому пути уже есть — заменяется, версия растёт.
    Тип — по расширению и содержимому (415); файл больше 20 МБ, текстовый больше 2 МБ,
    проект больше 200 МБ — 413; meta.tex — 403; на месте файла папка — 409.
    """
    checked = await service.check_uploads(form.folder, form.files)
    files = await service.save_uploads(session, storage, project.id, checked)
    return UploadResult(items=[_file_info(file) for file in files])


@router.post("/{pid}/move")
async def move(body: MoveRequest, project: OwnedProject, session: DbSession) -> FileInfo:
    """Перемещает или переименовывает файл или папку вместе с вложенными.

    Новый путь занят — 409; папку внутрь неё самой — 422; текстовый файл в тип не из 9.8 —
    415, картинку или документ в другой тип — тоже 415; сгенерированный файл (role=generated,
    например meta.tex) и папку с ним — 403. Версии файлов не меняются, а роль — по новому
    пути: перенесённое в materials/ становится материалом, из неё — обычным файлом.
    """
    moved = await service.move_path(session, project.id, body.from_, body.to)
    return _file_info(moved)
