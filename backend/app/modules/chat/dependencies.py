"""HTTP-часть чата: как разбудить воркер для прогона и прогон текущего пользователя."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.modules.auth.dependencies import CurrentUser
from app.modules.chat import service
from app.modules.chat.models import AgentRun
from app.modules.chat.tasks import Enqueue, enqueue_run


def get_run_enqueue() -> Enqueue:
    """Как отправить прогон воркеру: задача в очереди Redis. В тестах — подмена."""
    return enqueue_run


RunEnqueue = Annotated[Enqueue, Depends(get_run_enqueue)]


async def get_owned_run(rid: UUID, user: CurrentUser, session: DbSession) -> AgentRun:
    """Прогон {rid} из проекта текущего пользователя. Нет такого или проект чужой — 404."""
    run = await service.get_owned_run(session, rid, user.id)
    if run is None:
        raise AppError(ErrorCode.NOT_FOUND, service.RUN_NOT_FOUND_MESSAGE, 404)
    return run


OwnedRun = Annotated[AgentRun, Depends(get_owned_run)]
