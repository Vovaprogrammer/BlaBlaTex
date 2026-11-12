"""Схемы авторизации: регистрация, вход, текущий пользователь и личные токены."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, StringConstraints
from pydantic_core import PydanticCustomError

from app.core.text import NoNul
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


class AccountDelete(BaseModel):
    password: Annotated[Password, Field(min_length=1, description="Текущий пароль аккаунта")]


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


API_TOKEN_NAME_MAX_LENGTH = 100

ApiTokenName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=API_TOKEN_NAME_MAX_LENGTH),
    NoNul,
]


class ApiTokenCreate(BaseModel):
    name: ApiTokenName | None = Field(
        default=None,
        description="Подпись, по которой токен узнают в списке. Нет — сервер подпишет «Токен N»",
    )


class ApiTokenOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = Field(
        description="Когда токеном пользовались, с точностью до часа; null — ещё ни разу"
    )


class ApiTokenCreated(ApiTokenOut):
    token: str = Field(
        description="Значение bbt_pat_…: есть только в этом ответе, потом его не узнать"
    )


class ApiTokenList(BaseModel):
    items: list[ApiTokenOut] = Field(description="Рабочие токены, новые первыми")
