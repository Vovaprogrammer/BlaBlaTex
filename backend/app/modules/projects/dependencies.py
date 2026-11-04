"""HTTP-часть проектов: проект из адреса, если он принадлежит текущему пользователю,
и кто пишет файлы через сайт."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.core.events import EventsDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.projects import service
from app.modules.projects.history import Writer
from app.modules.projects.models import Project


async def get_owned_project(pid: UUID, user: CurrentUser, session: DbSession) -> Project:
    """Проект {pid} текущего пользователя. Нет такого или он чужой — 404.

    Ответ одинаковый, чтобы по нему нельзя было узнать, что чужой проект существует.
    """
    project = await service.get_owned_project(session, pid, user.id)
    if project is None:
        raise AppError(ErrorCode.NOT_FOUND, service.PROJECT_NOT_FOUND_MESSAGE, 404)
    return project


OwnedProject = Annotated[Project, Depends(get_owned_project)]


def get_user_writer(user: CurrentUser, events: EventsDep) -> Writer:
    """Правки через сайт: автор — студент, changeset выбирает сервис (раздел 5)."""
    return Writer(events, "user", user.id)


UserWriter = Annotated[Writer, Depends(get_user_writer)]
