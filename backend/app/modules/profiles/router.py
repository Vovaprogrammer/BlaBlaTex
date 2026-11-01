"""Профиль текущего пользователя."""

from fastapi import APIRouter

from app.core.db import DbSession
from app.modules.auth.dependencies import CurrentUser
from app.modules.profiles import service
from app.modules.profiles.schemas import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def get_profile(user: CurrentUser, session: DbSession) -> ProfileOut:
    """Профиль текущего пользователя."""
    profile = await service.get_profile(session, user.id)
    return ProfileOut.model_validate(profile, from_attributes=True)


@router.put("")
async def update_profile(body: ProfileUpdate, user: CurrentUser, session: DbSession) -> ProfileOut:
    """Сохраняет профиль целиком; из него собирается meta.tex проектов."""
    profile = await service.update_profile(session, user.id, body)
    return ProfileOut.model_validate(profile, from_attributes=True)
