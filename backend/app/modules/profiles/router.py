"""Профиль текущего пользователя."""

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.events import EventsDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.profiles import service
from app.modules.profiles.schemas import ProfileOut, ProfileUpdate
from app.modules.templates import service as templates_service
from app.modules.templates.dependencies import Templates

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def get_profile(user: CurrentUser, session: DbSession) -> ProfileOut:
    """Профиль текущего пользователя."""
    profile = await service.get_profile(session, user.id)
    return ProfileOut.model_validate(profile, from_attributes=True)


@router.put("")
async def update_profile(
    body: ProfileUpdate,
    user: CurrentUser,
    session: DbSession,
    templates: Templates,
    events: EventsDep,
) -> ProfileOut:
    """Сохраняет профиль целиком; из него собирается meta.tex проектов."""
    # meta.tex проектов пересоздаёт модуль шаблонов — в одной транзакции с профилем.
    profile = await templates_service.update_profile(session, events, user.id, body, templates)
    return ProfileOut.model_validate(profile, from_attributes=True)
