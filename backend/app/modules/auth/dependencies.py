"""HTTP-часть авторизации: cookie сессии, личные токены и текущий пользователь для роутов.

Браузер входит по cookie, агенты через MCP и скрипты — по заголовку
Authorization: Bearer bbt_pat_… (architecture.md 9.1). Есть заголовок — вход по токену,
даже если есть и cookie.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request, Response
from fastapi.security import APIKeyCookie, APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param

from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.core.ratelimit import Limit, get_rate_limiter
from app.modules.auth import service
from app.modules.auth.models import User

SESSION_COOKIE = "bbt_session"
# Имя cookie в проде (9.1): с приставкой __Host- браузер примет cookie только с Secure,
# Path=/ и без Domain — сайт на соседнем поддомене не подсунет студенту свою сессию.
# Локально сайт работает по http, а такой cookie нужен Secure, поэтому имя без приставки.
# Так и в установке на компьютере студента (APP_ENV=local, http://localhost): Chrome и Firefox
# приняли бы Secure-cookie на localhost, а Safari — нет, и студент на Mac не смог бы войти.
PROD_SESSION_COOKIE = f"__Host-{SESSION_COOKIE}"
CSRF_HEADER = "X-CSRF-Protection"
UNAUTHORIZED_MESSAGE = "Нужно войти в аккаунт"
CSRF_MESSAGE = "Запрос отклонён защитой от подделки. Обновите страницу и попробуйте ещё раз"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Тексты для агента: он пересказывает их студенту, поэтому в каждом — что делать.
TOKEN_MESSAGES = {
    service.TokenProblem.UNKNOWN: (
        "Токен не подошёл. Проверьте, что он скопирован целиком, "
        "или создайте новый в настройках BlaBlaTex"
    ),
    service.TokenProblem.REVOKED: "Токен удалён. Создайте новый в настройках BlaBlaTex",
    service.TokenProblem.IDLE: (
        f"Токеном не пользовались {service.API_TOKEN_IDLE_TTL.days} дней, и он отключён. "
        "Создайте новый в настройках BlaBlaTex"
    ),
}
BROWSER_ONLY_MESSAGE = "Это можно сделать только на сайте BlaBlaTex, а не по токену"
# Лимит на один токен (9.1): пока собирается PDF, агент спрашивает статус раз в секунду,
# остальное — чтение и правка файлов, в том числе пачками.
API_TOKEN_LIMIT = Limit(count=120, period_s=60)

# Описывает cookie в OpenAPI: у защищённых маршрутов в /api/docs появляется замок.
# Само значение читает session_token(): имя cookie в проде другое.
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description="Cookie сессии: ставится при регистрации и входе",
    auto_error=False,
)


def session_cookie_name(settings: Settings) -> str:
    """Имя cookie сессии: в проде — с приставкой __Host-, локально и в тестах — без неё."""
    return PROD_SESSION_COOKIE if settings.app_env == "prod" else SESSION_COOKIE


def _cookie_name(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return session_cookie_name(settings)


async def session_token(
    request: Request,
    # Только для OpenAPI: значение берётся по имени для окружения.
    _cookie: Annotated[str | None, Depends(session_cookie)],
) -> str | None:
    """Значение cookie сессии или None, если её нет."""
    return request.cookies.get(_cookie_name(request))


SessionToken = Annotated[str | None, Depends(session_token)]
# Описывает заголовок в OpenAPI: в /api/docs его можно один раз ввести через Authorize.
csrf_header = APIKeyHeader(
    name=CSRF_HEADER,
    scheme_name="csrf",
    description="Значение 1. Обязателен для POST, PUT, PATCH и DELETE с cookie сессии",
    auto_error=False,
)
# Описывает личный токен в OpenAPI. Сам заголовок разбирает bearer_token(): HTTPBearer
# пустое значение считает отсутствием заголовка, а агенту нужен ответ «Токен не подошёл».
api_token_header = HTTPBearer(
    scheme_name="token",
    description="Личный токен bbt_pat_… для агентов через MCP и скриптов",
    auto_error=False,
)


def bearer_token(request: Request) -> str | None:
    """Значение из Authorization: Bearer …; None — заголовка нет или он не Bearer.

    Пробелы и кавычки по краям убираются: с ними токен часто попадает в конфиг агента при
    копировании, и студент не должен разбираться, почему «токен не подошёл».
    """
    scheme, value = get_authorization_scheme_param(request.headers.get("Authorization"))
    return value.strip(" \t\"'") if scheme.lower() == "bearer" else None


def has_credentials(request: Request) -> bool:
    """Есть чем войти: cookie сессии или токен. Для проверок до чтения тела запроса."""
    return _cookie_name(request) in request.cookies or bearer_token(request) is not None


def _secure(request: Request) -> bool:
    # Secure — только в проде: локально и в тестах сервер работает по http.
    settings: Settings = request.app.state.settings
    return settings.app_env == "prod"


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    # Без domain: cookie только для этого хоста — это и требование приставки __Host-.
    response.set_cookie(
        _cookie_name(request),
        token,
        max_age=int(service.SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure(request),
    )


def delete_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        _cookie_name(request), path="/", httponly=True, samesite="lax", secure=_secure(request)
    )


def unauthorized() -> AppError:
    return AppError(ErrorCode.UNAUTHORIZED, UNAUTHORIZED_MESSAGE, 401)


@dataclass(frozen=True)
class Principal:
    """Кто делает запрос и как вошёл: от этого зависят автор правок и доступ к /tokens."""

    user: User
    via: Literal["session", "token"]


async def _token_principal(request: Request, session: DbSession, token: str) -> Principal:
    checked = await service.authenticate_api_token(session, token)
    if isinstance(checked, service.TokenProblem):
        raise AppError(
            ErrorCode.UNAUTHORIZED,
            TOKEN_MESSAGES[checked],
            401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    user, api_token = checked
    # Лимит считается по id токена, а не по значению: значение не должно попасть в Redis.
    await get_rate_limiter(request).check("api_token", str(api_token.id), API_TOKEN_LIMIT)
    return Principal(user, "token")


async def _session_user(
    request: Request, response: Response, session: DbSession, token: str | None
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


async def get_principal(
    request: Request,
    response: Response,
    session: DbSession,
    token: SessionToken,
    # Только для OpenAPI: значение берётся из bearer_token().
    _bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(api_token_header)],
) -> Principal:
    """Пользователь по токену из Authorization или по cookie.

    Неверный токен — 401 без попытки войти по cookie: агент должен узнать, что токен
    не работает. Нет ни токена, ни cookie, сессия истекла или удалена — 401.
    """
    api_token = bearer_token(request)
    if api_token is not None:
        return await _token_principal(request, session, api_token)
    return Principal(await _session_user(request, response, session, token), "session")


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def get_current_user(principal: CurrentPrincipal) -> User:
    """Пользователь, который делает запрос: из браузера или по токену."""
    return principal.user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_browser_user(
    request: Request, response: Response, session: DbSession, token: SessionToken
) -> User:
    """Пользователь, вошедший на сайте. С токеном в Authorization — 403, даже если есть
    и cookie: токенами и аккаунтом управляют только на сайте, чтобы утёкший токен не выпустил
    себе замену и не удалил аккаунт. Своя зависимость, а не get_principal: в OpenAPI у таких
    маршрутов только cookie."""
    if bearer_token(request) is not None:
        raise AppError(ErrorCode.FORBIDDEN, BROWSER_ONLY_MESSAGE, 403)
    return await _session_user(request, response, session, token)


BrowserUser = Annotated[User, Depends(get_browser_user)]


async def csrf_guard(request: Request, header: Annotated[str | None, Depends(csrf_header)]) -> None:
    """Небезопасный запрос с cookie сессии без заголовка X-CSRF-Protection: 1 — 403.

    Чужой сайт может заставить браузер отправить запрос с нашей cookie, но добавить свой
    заголовок без разрешения CORS не может. Запросы без cookie и с токеном в Authorization
    не проверяем: такой заголовок чужой сайт тоже не добавит, а вход по нему — не по cookie.
    """
    if request.method in SAFE_METHODS or _cookie_name(request) not in request.cookies:
        return
    if bearer_token(request) is not None:
        return
    if header != "1":
        raise AppError(ErrorCode.FORBIDDEN, CSRF_MESSAGE, 403)
