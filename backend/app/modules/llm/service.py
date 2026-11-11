"""Учёт расхода на ключе сервиса (architecture.md 5, 8)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

import structlog
from sqlalchemy import ColumnElement, Date, DateTime, cast, func, literal
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.llm.models import Usage

logger = structlog.get_logger(__name__)

# День квоты — по Москве: студент видит «лимит обновится в полночь». Летнего времени в
# Москве нет, но часовой пояс по имени считает сам Postgres.
QUOTA_TIMEZONE = "Europe/Moscow"


def quota_day(moment: ColumnElement[datetime] | datetime) -> ColumnElement[date]:
    """Дата по Москве для момента времени — в SQL, по таблице поясов Postgres."""
    if isinstance(moment, datetime):
        # У timezone() две версии — для времени с поясом и без; без явного типа Postgres
        # не выберет.
        moment = cast(literal(moment), DateTime(timezone=True))
    return cast(func.timezone(QUOTA_TIMEZONE, moment), Date)


async def record_usage(
    session: AsyncSession,
    user_id: uuid.UUID,
    run_id: uuid.UUID | None,
    tokens_in: int,
    tokens_out: int,
    cost: Decimal,
) -> None:
    """Прибавляет расход на ключе сервиса к строке студента за сегодня. Не коммитит.

    Один INSERT … ON CONFLICT: одновременные прогоны и описания не теряют расход друг друга.
    run_id есть — это прогон агента, и runs растёт на 1; у описания картинки run_id нет.
    Пользователя уже удалили — расход некому записать: в лог, без ошибки.
    """
    statement = insert(Usage).values(
        user_id=user_id,
        day=quota_day(func.now()),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        runs=0 if run_id is None else 1,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Usage.user_id, Usage.day],
        set_={
            "tokens_in": Usage.tokens_in + statement.excluded.tokens_in,
            "tokens_out": Usage.tokens_out + statement.excluded.tokens_out,
            "cost": Usage.cost + statement.excluded.cost,
            "runs": Usage.runs + statement.excluded.runs,
        },
    )
    try:
        # Точка сохранения: ошибка внешнего ключа не должна сломать транзакцию вызывающего.
        async with session.begin_nested():
            await session.execute(statement)
    except IntegrityError:
        logger.warning(
            "usage_user_missing",
            user_id=str(user_id),
            run_id=None if run_id is None else str(run_id),
        )
