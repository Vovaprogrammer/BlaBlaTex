"""Ограничения таблиц users и sessions на реальном Postgres."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User, UserSession

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_user(email: str = "student@example.com") -> User:
    return User(email=email, password_hash="hash", consent_at=NOW)


async def test_user_defaults_to_student_role(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()

    assert user.role == "student"


@pytest.mark.parametrize(
    "user",
    [
        make_user("Student@Example.com"),
        User(email="student@example.com", password_hash="hash", consent_at=NOW, role="root"),
    ],
    ids=["email not lowercase", "unknown role"],
)
async def test_database_rejects_invalid_user(db_session: AsyncSession, user: User) -> None:
    db_session.add(user)

    with pytest.raises(IntegrityError, match="ck_users_"):
        await db_session.flush()


async def test_email_is_unique(db_session: AsyncSession) -> None:
    db_session.add(make_user())
    await db_session.flush()
    db_session.add(make_user())

    with pytest.raises(IntegrityError, match="uq_users_email"):
        await db_session.flush()


async def test_deleting_user_deletes_sessions(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserSession(
            user_id=user.id,
            token_hash="0" * 64,
            expires_at=NOW + timedelta(days=30),
            last_seen_at=NOW,
        )
    )
    await db_session.flush()

    await db_session.execute(delete(User).where(User.id == user.id))

    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 0
