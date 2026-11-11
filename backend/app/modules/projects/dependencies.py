"""HTTP-часть проектов: проект из адреса, если он принадлежит текущему пользователю,
кто пишет файлы через сайт и где лежит общий класс для архива."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.core.events import Author, EventsDep
from app.modules.auth.dependencies import BrowserUser, CurrentPrincipal, CurrentUser
from app.modules.auth.models import User
from app.modules.materials.tasks import enqueue_extraction
from app.modules.projects import service
from app.modules.projects.export import SHARED_DIR_NAME
from app.modules.projects.history import ExtractMaterials, Writer
from app.modules.projects.models import Changeset, Project


async def get_owned_project(pid: UUID, user: CurrentUser, session: DbSession) -> Project:
    """Проект {pid} текущего пользователя. Нет такого или он чужой — 404.

    Ответ одинаковый, чтобы по нему нельзя было узнать, что чужой проект существует.
    """
    return await _owned_project(session, pid, user)


async def get_browser_owned_project(pid: UUID, user: BrowserUser, session: DbSession) -> Project:
    """Как get_owned_project, но только с сайта: по личному токену — 403 (9.1, «Авторизация»)."""
    return await _owned_project(session, pid, user)


async def _owned_project(session: AsyncSession, pid: UUID, user: User) -> Project:
    project = await service.get_owned_project(session, pid, user.id)
    if project is None:
        raise AppError(ErrorCode.NOT_FOUND, service.PROJECT_NOT_FOUND_MESSAGE, 404)
    return project


OwnedProject = Annotated[Project, Depends(get_owned_project)]
BrowserOwnedProject = Annotated[Project, Depends(get_browser_owned_project)]


def get_shared_dir(request: Request) -> Path:
    """Папка общего класса шаблонов: её файлы кладутся в архив проекта. В тестах — подмена."""
    settings: Settings = request.app.state.settings
    return settings.templates_dir / SHARED_DIR_NAME


SharedDir = Annotated[Path, Depends(get_shared_dir)]


async def get_owned_changeset(cid: UUID, user: CurrentUser, session: DbSession) -> Changeset:
    """Changeset {cid} из проекта текущего пользователя. Нет такого или проект чужой — 404."""
    changeset = await service.get_owned_changeset(session, cid, user.id)
    if changeset is None:
        raise AppError(ErrorCode.NOT_FOUND, service.CHANGESET_NOT_FOUND_MESSAGE, 404)
    return changeset


OwnedChangeset = Annotated[Changeset, Depends(get_owned_changeset)]


def get_extract_materials() -> ExtractMaterials:
    """Как разбудить извлечение текста материалов: задание воркеру. В тестах — подмена."""
    return enqueue_extraction


async def get_user_writer(
    principal: CurrentPrincipal,
    events: EventsDep,
    extract: Annotated[ExtractMaterials, Depends(get_extract_materials)],
) -> Writer:
    """Правки через API: с сайта автор — студент (user), по личному токену — агент через
    MCP (mcp). Так они не склеиваются в один changeset, и работу агента можно откатить
    отдельно (раздел 5). Изменённым материалам после commit ставится задание на извлечение
    текста."""
    author: Author = "mcp" if principal.via == "token" else "user"
    return Writer(events, author, principal.user.id, extract=extract)


UserWriter = Annotated[Writer, Depends(get_user_writer)]
