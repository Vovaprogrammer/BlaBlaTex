"""Схемы авторизации: регистрация, вход и текущий пользователь."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.modules.profiles.schemas import ProfileOut

UserRole = Literal["student", "teacher", "admin"]

# Верхняя граница не даёт отправить на хеширование огромную строку.
Password = Annotated[str, Field(max_length=128)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[Password, Field(min_length=8)]
    consent: Literal[True] = Field(description="Согласие на обработку персональных данных")


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
