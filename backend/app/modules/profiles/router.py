"""Профиль текущего пользователя. Пока заглушки: логику добавит B1.2."""

from fastapi import APIRouter

from app.core.errors import not_implemented
from app.modules.profiles.schemas import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def get_profile() -> ProfileOut:
    """Профиль текущего пользователя."""
    raise not_implemented()


@router.put("")
async def update_profile(body: ProfileUpdate) -> ProfileOut:
    """Сохраняет профиль целиком; из него собирается meta.tex проектов."""
    raise not_implemented()
