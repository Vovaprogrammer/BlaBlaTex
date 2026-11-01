"""Схемы профиля: данные студента для титульного листа."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

PROFILE_TEXT_MAX_LENGTH = 200

# Пустая строка — поле ещё не заполнено: профиль создаётся пустым при регистрации.
ProfileText = Annotated[str, Field(max_length=PROFILE_TEXT_MAX_LENGTH)]


class ProfileUpdate(BaseModel):
    """Профиль целиком: PUT заменяет все поля."""

    last_name: ProfileText
    first_name: ProfileText
    middle_name: ProfileText
    group_name: ProfileText
    faculty: ProfileText
    department: ProfileText


class ProfileOut(ProfileUpdate):
    updated_at: datetime
