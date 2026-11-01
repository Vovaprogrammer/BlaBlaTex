"""HTTP-часть авторизации: cookie bbt_session и текущий пользователь для роутов."""

from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.security import APIKeyCookie, APIKeyHeader

from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.modules.auth import service
from app.modules.auth.models import User

SESSION_COOKIE = "bbt_session"
CSRF_HEADER = "X-CSRF-Protection"
UNAUTHORIZED_MESSAGE = "Нужно войти в аккаунт"
CSRF_MESSAGE = "Запрос отклонён защитой от подделки. Обновите страницу и попробуйте ещё раз"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Описывает cookie в OpenAPI: у защищённых маршрутов в /api/docs появляется замок.
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description="Cookie сессии: ставится при регистрации и входе",
    auto_error=False,
)
SessionToken = Annotated[str | None, Depends(session_cookie)]
# Описывает заголовок в OpenAPI: в /api/docs его можно один раз ввести через Authorize.
csrf_header = APIKeyHeader(
    name=CSRF_HEADER,
    scheme_name="csrf",
    description="Значение 1. Обязателен для POST, PUT, PATCH и DELETE с cookie сессии",
    auto_error=False,
)


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


def unauthorized() -> AppError:
    return AppError(ErrorCode.UNAUTHORIZED, UNAUTHORIZED_MESSAGE, 401)


async def get_current_user(
    request: Request, response: Response, session: DbSession, token: SessionToken
) -> User:
    """Владелец cookie. Нет cookie, сессия истекла или удалена — 401."""
    if token is None:
        raise unauthorized()
    user = await service.authenticate(session, token)
    if user is None:
        raise unauthorized()
    # Срок cookie продлевается с каждым ответом, а не только когда сессию продлили в базе:
    # ответ с ошибкой или файлом заголовок теряет, и следующее продление было бы через час.
    set_session_cookie(request, response, token)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def csrf_guard(request: Request, header: Annotated[str | None, Depends(csrf_header)]) -> None:
    """Небезопасный запрос с cookie сессии без заголовка X-CSRF-Protection: 1 — 403.

    Чужой сайт может заставить браузер отправить запрос с нашей cookie, но добавить свой
    заголовок без разрешения CORS не может. Запросы без cookie (скрипты с токеном) не проверяем.
    """
    if request.method in SAFE_METHODS or SESSION_COOKIE not in request.cookies:
        return
    if header != "1":
        raise AppError(ErrorCode.FORBIDDEN, CSRF_MESSAGE, 403)
