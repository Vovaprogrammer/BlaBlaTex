"""Пароли и сессии входа. Здесь только логика, HTTP и cookie — в router.py."""

import asyncio
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.modules.auth.models import User, UserSession
from app.modules.profiles import service as profiles_service

SESSION_TTL = timedelta(days=30)
# Продлеваем сессию не чаще раза в час, иначе каждый запрос писал бы в базу.
SESSION_RENEW_INTERVAL = timedelta(hours=1)

EMAIL_TAKEN_MESSAGE = "Пользователь с таким email уже есть"
# Один текст для неизвестного email и неверного пароля: не раскрываем, кто зарегистрирован.
INVALID_CREDENTIALS_MESSAGE = "Неверный email или пароль"
# SQLSTATE «нарушена уникальность».
_UNIQUE_VIOLATION = "23505"

_password_hash = PasswordHash.recommended()
# Хеш случайного пароля для входа с неизвестным email. Считается при запуске, а не при
# первом таком входе: иначе тот запрос шёл бы вдвое дольше и выдавал, что email не найден.
_DUMMY_PASSWORD_HASH = _password_hash.hash(secrets.token_urlsafe(32))


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


def create_session(session: AsyncSession, user_id: uuid.UUID) -> str:
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


async def authenticate(session: AsyncSession, token: str) -> User | None:
    """Пользователь по токену из cookie или None, если сессии нет или она истекла.

    Срок скользящий: 30 дней с последнего визита, в базе продлевается не чаще раза в час.
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
    if now - user_session.last_seen_at >= SESSION_RENEW_INTERVAL:
        user_session.last_seen_at = now
        user_session.expires_at = now + SESSION_TTL
        await session.commit()
    return user


def normalize_email(email: str) -> str:
    return email.lower()


async def register(session: AsyncSession, email: str, password: str) -> tuple[User, str]:
    """Создаёт пользователя с пустым профилем и сразу входит.

    Возвращает пользователя и токен для cookie. Согласие на обработку ПД проверяет
    схема запроса, здесь сохраняется его время.
    """
    user = User(
        email=normalize_email(email),
        password_hash=await hash_password(password),
        consent_at=_utcnow(),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        # Повториться может только email: id — случайный uuid.
        if getattr(error.orig, "pgcode", None) == _UNIQUE_VIOLATION:
            raise AppError(ErrorCode.ALREADY_EXISTS, EMAIL_TAKEN_MESSAGE, 409) from error
        raise
    profiles_service.create_empty_profile(session, user.id)
    token = create_session(session, user.id)
    await session.commit()
    return user, token


async def login(session: AsyncSession, email: str, password: str) -> tuple[User, str]:
    """Вход по email и паролю. Возвращает пользователя и токен новой сессии для cookie."""
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        # Проверка пароля занимает столько же, сколько настоящая: по времени ответа
        # нельзя понять, зарегистрирован ли email.
        await verify_password(password, _DUMMY_PASSWORD_HASH)
        raise AppError(ErrorCode.UNAUTHORIZED, INVALID_CREDENTIALS_MESSAGE, 401)
    ok, new_hash = await verify_password(password, user.password_hash)
    if not ok:
        raise AppError(ErrorCode.UNAUTHORIZED, INVALID_CREDENTIALS_MESSAGE, 401)
    if new_hash is not None:
        user.password_hash = new_hash
    token = create_session(session, user.id)
    await session.commit()
    return user, token


async def delete_session(session: AsyncSession, token: str) -> None:
    """Завершает сессию. Неизвестный токен — не ошибка: повторный выход ничего не ломает."""
    await session.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))
    await session.commit()
