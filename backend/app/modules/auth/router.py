"""Регистрация, вход, выход, текущий пользователь и личные токены."""

from uuid import UUID

from fastapi import APIRouter, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import DbSession
from app.modules.auth import limits, service
from app.modules.auth.dependencies import (
    BrowserUser,
    CurrentUser,
    SessionToken,
    delete_session_cookie,
    set_session_cookie,
)
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenList,
    ApiTokenOut,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    UserOut,
)
from app.modules.profiles import service as profiles_service
from app.modules.profiles.schemas import ProfileOut

router = APIRouter(prefix="/auth", tags=["auth"])
# Личные токены для агентов через MCP и скриптов (architecture.md 9.1). Только с сайта:
# по токену — 403, чтобы утёкший токен не выпустил себе замену.
tokens_router = APIRouter(prefix="/tokens", tags=["tokens"])


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
    """Создаёт пользователя с пустым профилем и сразу входит: ставит cookie сессии.

    Не больше 30 регистраций в час с одного IP — сверх 429."""
    await limits.check_registration(request)
    user, token = await service.register(session, body.email, body.password)
    set_session_cookie(request, response, token)
    return await _me(session, user)


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, session: DbSession
) -> MeResponse:
    """Вход по email и паролю: ставит cookie сессии.

    Неудачные попытки ограничены (architecture.md 9.1): лимит исчерпан или счётчики
    недоступны — 429, пароль не проверяется."""
    counters = limits.password_counters(request, body.email)
    await limits.check_password_attempts(request, counters)
    try:
        user, token = await service.login(session, body.email, body.password)
    except service.WrongPasswordError:
        await limits.count_failed_attempt(request, counters)
        raise
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


@tokens_router.get("")
async def list_tokens(user: BrowserUser, session: DbSession) -> ApiTokenList:
    """Рабочие токены пользователя, новые первыми. Значений токенов в списке нет."""
    tokens = await service.list_api_tokens(session, user.id)
    return ApiTokenList(
        items=[ApiTokenOut.model_validate(token, from_attributes=True) for token in tokens]
    )


@tokens_router.post("", status_code=201)
async def create_token(
    body: ApiTokenCreate, user: BrowserUser, session: DbSession
) -> ApiTokenCreated:
    """Новый токен. Его значение есть только в этом ответе. Рабочих уже 20 — 403."""
    api_token, token = await service.create_api_token(session, user.id, body.name)
    out = ApiTokenOut.model_validate(api_token, from_attributes=True)
    return ApiTokenCreated(**out.model_dump(), token=token)


@tokens_router.delete("/{tid}", status_code=204)
async def delete_token(tid: UUID, user: BrowserUser, session: DbSession) -> None:
    """Удаляет токен: он сразу перестаёт работать. Чужой или уже удалённый — 404."""
    await service.revoke_api_token(session, user.id, tid)
