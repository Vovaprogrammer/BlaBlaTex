"""Пароли и сессии входа. Здесь только логика, HTTP и cookie — в router.py."""

import asyncio
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User, UserSession

SESSION_TTL = timedelta(days=30)
# Продлеваем сессию не чаще раза в час, иначе каждый запрос писал бы в базу.
SESSION_RENEW_INTERVAL = timedelta(hours=1)

_password_hash = PasswordHash.recommended()


async def hash_password(password: str) -> str:
    """Хеш argon2. Считается в отдельном потоке: это десятки миллисекунд процессора."""
    return await asyncio.to_thread(_password_hash.hash, password)


async def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Проверяет пароль. Второе значение — новый хеш, если параметры argon2 устарели."""
    return await asyncio.to_thread(_password_hash.verify_and_update, password, password_hash)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def create_session(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Добавляет сессию и возвращает токен для cookie. В базе — только sha256 токена.

    Коммит — за вызывающим: при регистрации сессия создаётся в одной транзакции с пользователем.
    """
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    session.add(
        UserSession(
            user_id=user_id,
            token_hash=_hash_token(token),
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
        )
    )
    return token


@dataclass(frozen=True, slots=True)
class Authenticated:
    """Владелец cookie. renewed — срок сессии только что продлён, cookie надо выдать заново."""

    user: User
    renewed: bool


async def authenticate(session: AsyncSession, token: str) -> Authenticated | None:
    """Пользователь по токену из cookie или None, если сессии нет или она истекла.

    Срок скользящий: 30 дней с последнего визита.
    """
    now = _utcnow()
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == _hash_token(token), UserSession.expires_at > now)
        )
    ).one_or_none()
    if row is None:
        return None
    user_session, user = row
    if now - user_session.last_seen_at < SESSION_RENEW_INTERVAL:
        return Authenticated(user=user, renewed=False)
    user_session.last_seen_at = now
    user_session.expires_at = now + SESSION_TTL
    await session.commit()
    return Authenticated(user=user, renewed=True)


async def delete_session(session: AsyncSession, token: str) -> None:
    """Завершает сессию. Неизвестный токен — не ошибка: повторный выход ничего не ломает."""
    await session.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))
    await session.commit()
