"""Профиль студента. Другие модули работают с таблицей profiles только через эти функции."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.models import Profile
from app.modules.profiles.schemas import ProfileUpdate


def create_empty_profile(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    """Пустой профиль нового пользователя. Коммит — за регистрацией, в одной транзакции."""
    profile = Profile(user_id=user_id)
    session.add(profile)
    return profile


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    # Профиль есть у каждого пользователя: он создаётся вместе с ним.
    return await session.get_one(Profile, user_id)


async def update_profile(session: AsyncSession, user_id: uuid.UUID, data: ProfileUpdate) -> Profile:
    """Заменяет все поля профиля."""
    profile = await get_profile(session, user_id)
    for field, value in data.model_dump().items():
        setattr(profile, field, value)
    await session.commit()
    return profile
