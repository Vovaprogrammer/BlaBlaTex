"""HTTP-часть сборок: как разбудить воркер и сборка из адреса."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.modules.auth.dependencies import CurrentUser
from app.modules.builds import service
from app.modules.builds.compiler import CompilerClient
from app.modules.builds.models import Build
from app.modules.builds.tasks import Enqueue, enqueue_build

BUILD_NOT_FOUND_MESSAGE = "Сборка не найдена"


def get_enqueue() -> Enqueue:
    """Как отправить сборку воркеру: задача в очереди Redis. В тестах — подмена get_enqueue."""
    return enqueue_build


async def get_owned_build(bid: UUID, user: CurrentUser, session: DbSession) -> Build:
    """Сборка {bid} из проекта текущего пользователя. Нет такой или она чужая — 404."""
    build = await service.get_owned_build(session, bid, user.id)
    if build is None:
        raise AppError(ErrorCode.NOT_FOUND, BUILD_NOT_FOUND_MESSAGE, 404)
    return build


def get_api_compiler(request: Request) -> CompilerClient | None:
    """Клиент компилятора в API: по версии из /health проверки находят сборку текущих
    файлов (9.1). Его создаёт lifespan; без lifespan (тесты) — None, и проверки просто
    ставят сборку."""
    compiler: CompilerClient | None = getattr(request.app.state, "compiler", None)
    return compiler


BuildEnqueue = Annotated[Enqueue, Depends(get_enqueue)]
OwnedBuild = Annotated[Build, Depends(get_owned_build)]
ApiCompiler = Annotated[CompilerClient | None, Depends(get_api_compiler)]
