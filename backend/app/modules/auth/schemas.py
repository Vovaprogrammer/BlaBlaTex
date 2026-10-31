"""Схемы авторизации: регистрация, вход и текущий пользователь."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, EmailStr, Field
from pydantic_core import PydanticCustomError

from app.modules.profiles.schemas import ProfileOut

UserRole = Literal["student", "teacher", "admin"]

# Верхняя граница не даёт отправить на хеширование огромную строку.
Password = Annotated[str, Field(max_length=128)]


def _only_bool(value: object) -> object:
    # Literal[True] сам пропускает 1 и 1.0 (в Python 1 == True), а согласие — только явное true.
    if not isinstance(value, bool):
        raise PydanticCustomError("literal_error", "Input should be True")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[Password, Field(min_length=8)]
    consent: Annotated[Literal[True], BeforeValidator(_only_bool)] = Field(
        description="Согласие на обработку персональных данных"
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[Password, Field(min_length=1)]


class UserOut(BaseModel):
    id: UUID
    email: str
    role: UserRole
    created_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    profile: ProfileOut
