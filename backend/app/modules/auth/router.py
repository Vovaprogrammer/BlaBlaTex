"""Регистрация, вход, выход и текущий пользователь."""

from fastapi import APIRouter, Request, Response

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
from app.modules.profiles.schemas import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/auth", tags=["auth"])


def _me(user: User) -> MeResponse:
    # Таблицы профилей ещё нет — отдаём пустой профиль, каким он создаётся при регистрации.
    profile = ProfileOut(
        **dict.fromkeys(ProfileUpdate.model_fields, ""), updated_at=user.created_at
    )
    return MeResponse(user=UserOut.model_validate(user, from_attributes=True), profile=profile)


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest, request: Request, response: Response, session: DbSession
) -> MeResponse:
    """Создаёт пользователя с пустым профилем и сразу входит: ставит cookie bbt_session."""
    user, token = await service.register(session, body.email, body.password)
    set_session_cookie(request, response, token)
    return _me(user)


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, session: DbSession
) -> MeResponse:
    """Вход по email и паролю: ставит cookie bbt_session."""
    user, token = await service.login(session, body.email, body.password)
    set_session_cookie(request, response, token)
    return _me(user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: DbSession, token: SessionToken
) -> None:
    """Завершает текущую сессию и удаляет cookie. Без сессии тоже отвечает 204."""
    if token is not None:
        await service.delete_session(session, token)
    delete_session_cookie(request, response)


@router.get("/me")
async def me(user: CurrentUser) -> MeResponse:
    """Текущий пользователь и его профиль."""
    return _me(user)
