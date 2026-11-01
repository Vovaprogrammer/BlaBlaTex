"""Регистрация, вход, выход и текущий пользователь."""

from fastapi import APIRouter, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import DbSession
from app.modules.auth import service
from app.modules.auth.dependencies import (
    CurrentUser,
    SessionToken,
    delete_session_cookie,
    set_session_cookie,
)
from app.modules.auth.models import User
from app.modules.auth.schemas import LoginRequest, MeResponse, RegisterRequest, UserOut
from app.modules.profiles import service as profiles_service
from app.modules.profiles.schemas import ProfileOut

router = APIRouter(prefix="/auth", tags=["auth"])


async def _me(session: AsyncSession, user: User) -> MeResponse:
    profile = await profiles_service.get_profile(session, user.id)
    return MeResponse(
        user=UserOut.model_validate(user, from_attributes=True),
        profile=ProfileOut.model_validate(profile, from_attributes=True),
    )


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest, request: Request, response: Response, session: DbSession
) -> MeResponse:
    """Создаёт пользователя с пустым профилем и сразу входит: ставит cookie bbt_session."""
    user, token = await service.register(session, body.email, body.password)
    set_session_cookie(request, response, token)
    return await _me(session, user)


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, session: DbSession
) -> MeResponse:
    """Вход по email и паролю: ставит cookie bbt_session."""
    user, token = await service.login(session, body.email, body.password)
    set_session_cookie(request, response, token)
    return await _me(session, user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: DbSession, token: SessionToken
) -> None:
    """Завершает текущую сессию и удаляет cookie. Без сессии тоже отвечает 204."""
    if token is not None:
        await service.delete_session(session, token)
    delete_session_cookie(request, response)


@router.get("/me")
async def me(user: CurrentUser, session: DbSession) -> MeResponse:
    """Текущий пользователь и его профиль."""
    return await _me(session, user)
