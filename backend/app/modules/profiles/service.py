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


async def get_profile(session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> Profile:
    """Профиль пользователя; он есть у каждого — создаётся вместе с ним.

    lock — заблокировать строку до конца транзакции и перечитать её из базы. Так meta.tex
    собирается из профиля, который никто не поменяет, пока транзакция не закончится:
    правка профиля и создание или правка проекта не разойдутся при одновременных запросах.
    """
    if lock:
        return await session.get_one(Profile, user_id, with_for_update=True, populate_existing=True)
    return await session.get_one(Profile, user_id)


async def update_profile(session: AsyncSession, user_id: uuid.UUID, data: ProfileUpdate) -> Profile:
    """Заменяет все поля профиля. Коммит — за вызывающим: вместе с профилем в той же
    транзакции пересоздаётся meta.tex проектов (templates.service.update_profile)."""
    profile = await get_profile(session, user_id, lock=True)
    for field, value in data.model_dump().items():
        setattr(profile, field, value)
    return profile
