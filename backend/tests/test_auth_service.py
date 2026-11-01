"""Хеши паролей и сессии входа на уровне сервиса."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service
from app.modules.auth.models import User, UserSession


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    user = User(email="student@example.com", password_hash="hash", consent_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    return user


async def stored_session(db_session: AsyncSession) -> UserSession:
    return (await db_session.scalars(select(UserSession))).one()


async def test_password_hash_is_argon2_and_verifies() -> None:
    password_hash = await service.hash_password("password1")

    assert password_hash.startswith("$argon2id$")
    assert "password1" not in password_hash
    assert await service.verify_password("password1", password_hash) == (True, None)
    assert await service.verify_password("password2", password_hash) == (False, None)


async def test_outdated_password_hash_is_replaced_on_verify() -> None:
    old_hash = Argon2Hasher(time_cost=1).hash("password1")

    ok, new_hash = await service.verify_password("password1", old_hash)

    assert ok
    assert new_hash is not None
    assert await service.verify_password("password1", new_hash) == (True, None)


async def test_session_token_is_stored_only_as_sha256(db_session: AsyncSession, user: User) -> None:
    token = await service.create_session(db_session, user.id)
    await db_session.flush()

    stored = await stored_session(db_session)
    assert len(token) >= 43  # 32 случайных байта в base64url
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert stored.expires_at - stored.last_seen_at == service.SESSION_TTL


async def test_fresh_session_authenticates_without_renewal(
    db_session: AsyncSession, user: User
) -> None:
    token = await service.create_session(db_session, user.id)
    await db_session.flush()
    expires_at = (await stored_session(db_session)).expires_at

    result = await service.authenticate(db_session, token)

    assert result == service.Authenticated(user=user, renewed=False)
    assert (await stored_session(db_session)).expires_at == expires_at


async def test_stale_session_is_renewed_for_full_ttl(db_session: AsyncSession, user: User) -> None:
    token = await service.create_session(db_session, user.id)
    stored = await stored_session(db_session)
    # Последний визит 29 дней назад: до конца срока остался день.
    stored.last_seen_at -= timedelta(days=29)
    stored.expires_at -= timedelta(days=29)
    await db_session.flush()

    result = await service.authenticate(db_session, token)

    assert result == service.Authenticated(user=user, renewed=True)
    assert stored.expires_at - datetime.now(UTC) > service.SESSION_TTL - timedelta(minutes=1)


async def test_expired_session_is_rejected(db_session: AsyncSession, user: User) -> None:
    token = await service.create_session(db_session, user.id)
    stored = await stored_session(db_session)
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    assert await service.authenticate(db_session, token) is None


async def test_unknown_token_is_rejected(db_session: AsyncSession, user: User) -> None:
    await service.create_session(db_session, user.id)
    await db_session.flush()

    assert await service.authenticate(db_session, "not-a-token") is None


async def test_deleted_session_no_longer_authenticates(
    db_session: AsyncSession, user: User
) -> None:
    token = await service.create_session(db_session, user.id)
    await db_session.flush()

    await service.delete_session(db_session, token)

    assert await service.authenticate(db_session, token) is None
    assert (await db_session.scalars(select(UserSession))).all() == []
