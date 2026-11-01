"""HTTP-часть сборок: клиент компилятора приложения и сборка из адреса."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.modules.auth.dependencies import CurrentUser
from app.modules.builds import service
from app.modules.builds.compiler import CompilerClient
from app.modules.builds.models import Build

BUILD_NOT_FOUND_MESSAGE = "Сборка не найдена"


def get_compiler(request: Request) -> CompilerClient:
    """Клиент компилятора; его создаёт lifespan из create_app()."""
    compiler: CompilerClient | None = getattr(request.app.state, "compiler", None)
    if compiler is None:
        raise RuntimeError(
            "Нет клиента компилятора: lifespan приложения не запущен. "
            "В тестах — подмена get_compiler."
        )
    return compiler


async def get_owned_build(bid: UUID, user: CurrentUser, session: DbSession) -> Build:
    """Сборка {bid} из проекта текущего пользователя. Нет такой или она чужая — 404."""
    build = await service.get_owned_build(session, bid, user.id)
    if build is None:
        raise AppError(ErrorCode.NOT_FOUND, BUILD_NOT_FOUND_MESSAGE, 404)
    return build


Compiler = Annotated[CompilerClient, Depends(get_compiler)]
OwnedBuild = Annotated[Build, Depends(get_owned_build)]
