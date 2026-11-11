"""Учёт расхода на ключе сервиса (architecture.md 5): строка студента за день по Москве."""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.llm import service
from app.modules.llm.models import Usage
from tests.live_builds import Live


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    user = User(email="student@example.com", password_hash="hash", consent_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    return user


async def usage_rows(session: AsyncSession, user_id: uuid.UUID) -> list[Usage]:
    rows = await session.scalars(
        select(Usage)
        .where(Usage.user_id == user_id)
        .order_by(Usage.day)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def today(session: AsyncSession) -> date:
    day = await session.scalar(select(service.quota_day(func.now())))
    assert day is not None
    return day


async def test_runs_and_descriptions_add_up_in_one_row(
    db_session: AsyncSession, user: User
) -> None:
    await service.record_usage(db_session, user.id, uuid.uuid4(), 1000, 200, Decimal("0.01"))
    await service.record_usage(db_session, user.id, uuid.uuid4(), 500, 100, Decimal("0.005"))
    # Описание картинки — без прогона: токены есть, прогона нет.
    await service.record_usage(db_session, user.id, None, 900, 40, Decimal("0.001"))

    [row] = await usage_rows(db_session, user.id)
    assert (row.day, row.tokens_in, row.tokens_out, row.cost, row.runs) == (
        await today(db_session),
        2400,
        340,
        Decimal("0.016"),
        2,
    )


async def test_new_day_starts_new_row(db_session: AsyncSession, user: User) -> None:
    yesterday = await today(db_session) - timedelta(days=1)
    db_session.add(Usage(user_id=user.id, day=yesterday, tokens_in=7, tokens_out=3, runs=1))
    await db_session.flush()

    await service.record_usage(db_session, user.id, uuid.uuid4(), 10, 5, Decimal(0))

    rows = await usage_rows(db_session, user.id)
    assert [(row.day, row.tokens_in, row.runs) for row in rows] == [
        (yesterday, 7, 1),
        (await today(db_session), 10, 1),
    ]


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 11, 11, 0, 30, tzinfo=UTC), date(2026, 11, 11)),
        (datetime(2026, 11, 11, 20, 59, 59, tzinfo=UTC), date(2026, 11, 11)),
        # Полночь по Москве — 21:00 UTC: начинается следующий день.
        (datetime(2026, 11, 11, 21, 0, tzinfo=UTC), date(2026, 11, 12)),
        (datetime(2026, 6, 30, 21, 0, tzinfo=UTC), date(2026, 7, 1)),
    ],
    ids=["night-utc", "last-moscow-second", "moscow-midnight", "summer"],
)
async def test_day_is_moscow_date(
    db_session: AsyncSession, moment: datetime, expected: date
) -> None:
    assert await db_session.scalar(select(service.quota_day(moment))) == expected


async def test_usage_of_deleted_user_is_skipped(db_session: AsyncSession, user: User) -> None:
    # Студент удалил аккаунт, пока шёл прогон: записать некуда, но транзакция цела.
    await service.record_usage(db_session, uuid.uuid4(), uuid.uuid4(), 10, 5, Decimal(0))
    await service.record_usage(db_session, user.id, None, 1, 1, Decimal(0))

    [row] = await usage_rows(db_session, user.id)
    assert row.tokens_in == 1


async def test_failed_usage_write_does_not_break_transaction(
    db_session: AsyncSession, user: User
) -> None:
    # Число не помещается в колонку: учёт не записан, а итог прогона в той же транзакции цел.
    await service.record_usage(db_session, user.id, uuid.uuid4(), 2**31, 0, Decimal(0))
    await service.record_usage(db_session, user.id, None, 1, 1, Decimal(0))

    [row] = await usage_rows(db_session, user.id)
    assert row.tokens_in == 1


async def test_parallel_records_lose_nothing(live: Live) -> None:
    async def record() -> None:
        async with live.sessionmaker() as session:
            await service.record_usage(session, live.owner_id, uuid.uuid4(), 100, 10, Decimal(1))
            await session.commit()

    await asyncio.gather(*(record() for _ in range(10)))

    async with live.sessionmaker() as session:
        [row] = await usage_rows(session, live.owner_id)
    assert (row.tokens_in, row.tokens_out, row.cost, row.runs) == (1000, 100, Decimal(10), 10)
