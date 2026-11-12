"""Пароли, сессии входа и личные токены. Здесь только логика, HTTP и cookie — в router.py."""

import asyncio
import hashlib
import secrets
import string
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pwdlib import PasswordHash
from sqlalchemy import ColumnElement, and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.modules.auth.models import ApiToken, User, UserSession
from app.modules.profiles import service as profiles_service

SESSION_TTL = timedelta(days=30)
# Продлеваем сессию не чаще раза в час, иначе каждый запрос писал бы в базу.
SESSION_RENEW_INTERVAL = timedelta(hours=1)

EMAIL_TAKEN_MESSAGE = "Пользователь с таким email уже есть"
# Один текст для неизвестного email и неверного пароля: не раскрываем, кто зарегистрирован.
INVALID_CREDENTIALS_MESSAGE = "Неверный email или пароль"


class WrongPasswordError(AppError):
    """Неверная почта или пароль. Роутер засчитывает такую попытку в лимиты входа (limits.py)."""


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
        raise WrongPasswordError(ErrorCode.UNAUTHORIZED, INVALID_CREDENTIALS_MESSAGE, 401)
    ok, new_hash = await verify_password(password, user.password_hash)
    if not ok:
        raise WrongPasswordError(ErrorCode.UNAUTHORIZED, INVALID_CREDENTIALS_MESSAGE, 401)
    if new_hash is not None:
        user.password_hash = new_hash
    token = create_session(session, user.id)
    await session.commit()
    return user, token


async def delete_session(session: AsyncSession, token: str) -> None:
    """Завершает сессию. Неизвестный токен — не ошибка: повторный выход ничего не ломает."""
    await session.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))
    await session.commit()


# Личные токены (architecture.md 9.1). По приставке токен узнают в выложенном конфиге.
API_TOKEN_PREFIX = "bbt_pat_"
API_TOKEN_RANDOM_BYTES = 32
# 62**43 > 2**256: 43 знака base62 хватает на любые 32 байта, короче — не на все.
API_TOKEN_BODY_LENGTH = 43
_BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase
# Токен, которым столько не пользовались, отключается сам: забытый в старом конфиге
# перестаёт работать, а кто работает с агентом, этого не заметит.
API_TOKEN_IDLE_TTL = timedelta(days=90)
API_TOKENS_MAX = 20

TOO_MANY_TOKENS_MESSAGE = (
    f"Можно создать не больше {API_TOKENS_MAX} токенов. Удалите ненужный в настройках"
)
TOKEN_NOT_FOUND_MESSAGE = "Токен не найден"


def generate_api_token() -> str:
    """bbt_pat_ и 32 случайных байта в base62 — всегда 43 знака, с ведущими нулями."""
    number = int.from_bytes(secrets.token_bytes(API_TOKEN_RANDOM_BYTES))
    digits = []
    for _ in range(API_TOKEN_BODY_LENGTH):
        number, digit = divmod(number, len(_BASE62))
        digits.append(_BASE62[digit])
    return API_TOKEN_PREFIX + "".join(reversed(digits))


def _token_works(now: datetime) -> ColumnElement[bool]:
    """Токен не удалён и не отключён: им пользовались (или создали) меньше 90 дней назад."""
    return and_(
        ApiToken.revoked_at.is_(None),
        func.coalesce(ApiToken.last_used_at, ApiToken.created_at) > now - API_TOKEN_IDLE_TTL,
    )


async def create_api_token(
    session: AsyncSession, user_id: uuid.UUID, name: str | None
) -> tuple[ApiToken, str]:
    """Создаёт токен и возвращает его строку и значение. Значение больше нигде не узнать.

    Без подписи токен называется «Токен N», где N — сколько токенов студент создал, считая
    этот. Рабочих токенов уже API_TOKENS_MAX — 403.
    """
    # Строка пользователя блокируется до commit: два одновременных запроса не создадут
    # 21-й токен и не получат одинаковый номер в подписи. FOR NO KEY UPDATE, а не FOR UPDATE:
    # вход и создание проекта в это время не ждут — их внешний ключ на users не мешает.
    await session.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    now = _utcnow()
    working, created = (
        await session.execute(
            select(func.count().filter(_token_works(now)), func.count())
            .select_from(ApiToken)
            .where(ApiToken.user_id == user_id)
        )
    ).one()
    if working >= API_TOKENS_MAX:
        await session.rollback()
        raise AppError(ErrorCode.FORBIDDEN, TOO_MANY_TOKENS_MESSAGE, 403)
    if name is None:
        name = f"Токен {created + 1}"
    token = generate_api_token()
    api_token = ApiToken(user_id=user_id, name=name, token_hash=_hash_token(token), created_at=now)
    session.add(api_token)
    await session.commit()
    return api_token, token


async def list_api_tokens(session: AsyncSession, user_id: uuid.UUID) -> Sequence[ApiToken]:
    """Рабочие токены пользователя, новые первыми."""
    result = await session.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == user_id, _token_works(_utcnow()))
        .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
    )
    return result.all()


class TokenProblem(StrEnum):
    """Почему токен не подошёл: от этого зависит, что сказать студенту."""

    UNKNOWN = "unknown"
    REVOKED = "revoked"
    IDLE = "idle"


async def authenticate_api_token(
    session: AsyncSession, token: str
) -> tuple[User, ApiToken] | TokenProblem:
    """Владелец токена и сам токен или причина, почему токен не подошёл.

    last_used_at, а с ним и 90-дневный срок обновляются не чаще раза в час, как у сессии:
    иначе каждый запрос агента писал бы в базу.
    """
    if not token.startswith(API_TOKEN_PREFIX):
        return TokenProblem.UNKNOWN
    row = (
        await session.execute(
            select(ApiToken, User)
            .join(User, User.id == ApiToken.user_id)
            .where(ApiToken.token_hash == _hash_token(token))
        )
    ).one_or_none()
    if row is None:
        return TokenProblem.UNKNOWN
    api_token, user = row
    if api_token.revoked_at is not None:
        return TokenProblem.REVOKED
    now = _utcnow()
    # То же условие, что _token_works в SQL: список и вход не расходятся.
    if now - (api_token.last_used_at or api_token.created_at) >= API_TOKEN_IDLE_TTL:
        return TokenProblem.IDLE
    if api_token.last_used_at is None or now - api_token.last_used_at >= SESSION_RENEW_INTERVAL:
        api_token.last_used_at = now
        await session.commit()
    return user, api_token


async def revoke_api_token(session: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    """Удаляет токен: он сразу перестаёт работать. Чужой, нет такого или уже не работает — 404."""
    now = _utcnow()
    revoked = await session.scalar(
        update(ApiToken)
        .where(ApiToken.id == token_id, ApiToken.user_id == user_id, _token_works(now))
        .values(revoked_at=now)
        .returning(ApiToken.id)
    )
    if revoked is None:
        await session.rollback()
        raise AppError(ErrorCode.NOT_FOUND, TOKEN_NOT_FOUND_MESSAGE, 404)
    await session.commit()
