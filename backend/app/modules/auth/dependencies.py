"""HTTP-часть авторизации: cookie bbt_session и текущий пользователь для роутов."""

from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.security import APIKeyCookie

from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.modules.auth import service
from app.modules.auth.models import User

SESSION_COOKIE = "bbt_session"
UNAUTHORIZED_MESSAGE = "Нужно войти в аккаунт"

# Описывает cookie в OpenAPI: у защищённых маршрутов в /api/docs появляется замок.
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description="Cookie сессии: ставится при регистрации и входе",
    auto_error=False,
)
SessionToken = Annotated[str | None, Depends(session_cookie)]


def _secure(request: Request) -> bool:
    # Secure — только в проде: локально и в тестах сервер работает по http.
    settings: Settings = request.app.state.settings
    return settings.app_env == "prod"


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(service.SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=_secure(request),
    )


def delete_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax", secure=_secure(request))


def _unauthorized() -> AppError:
    return AppError(ErrorCode.UNAUTHORIZED, UNAUTHORIZED_MESSAGE, 401)


async def get_current_user(
    request: Request, response: Response, session: DbSession, token: SessionToken
) -> User:
    """Владелец cookie. Нет cookie, сессия истекла или удалена — 401."""
    if token is None:
        raise _unauthorized()
    authenticated = await service.authenticate(session, token)
    if authenticated is None:
        raise _unauthorized()
    if authenticated.renewed:
        # Срок сессии продлён — продлеваем и cookie, иначе браузер удалит её раньше.
        set_session_cookie(request, response, token)
    return authenticated.user


CurrentUser = Annotated[User, Depends(get_current_user)]
