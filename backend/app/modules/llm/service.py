"""Свой ключ LLM студента и учёт расхода на ключе сервиса (architecture.md 5, 8, 9.1)."""

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

import httpx
import structlog
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import SecretStr, TypeAdapter
from sqlalchemy import ColumnElement, Date, DateTime, cast, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import LLMProviderSettings, Settings
from app.core.errors import AppError, ErrorCode, request_error
from app.modules.llm.models import LlmKey, Usage

logger = structlog.get_logger(__name__)

# Ключ — одна строка видимых символов ASCII: иначе его не передать в заголовке HTTP.
KEY_MIN_LENGTH = 8
KEY_MAX_LENGTH = 500
KEY_PATTERN = re.compile(r"[\x21-\x7e]+")
# Сколько ждать ответ провайдера на пробный запрос: студент ждёт его в форме.
KEY_CHECK_TIMEOUT_S = 20.0

KEY_FORMAT_MESSAGE = (
    "Ключ — одна строка из латинских букв, цифр и знаков, без пробелов. "
    "Скопируйте его из кабинета провайдера целиком"
)
KEY_LENGTH_MESSAGE = f"Длина ключа — от {KEY_MIN_LENGTH} до {KEY_MAX_LENGTH} символов"
KEY_REJECTED_MESSAGE = (
    "Ключ не подошёл: провайдер его не принял. Проверьте, что ключ скопирован целиком "
    "и не удалён в кабинете провайдера"
)
KEY_NO_FUNDS_MESSAGE = (
    "На счёте этого ключа нет денег. Пополните баланс у провайдера и сохраните ключ снова"
)
KEY_UNAVAILABLE_MESSAGE = "Не удалось проверить ключ: провайдер не отвечает. Попробуйте позже"
LLM_NOT_CONFIGURED_MESSAGE = "ИИ на сервере не настроен, поэтому свой ключ пока не сохранить"
ENCRYPTION_MISSING_MESSAGE = "Свой ключ сейчас нельзя сохранить: на сервере не настроено шифрование"
QUOTA_MESSAGE = (
    "Дневной лимит ИИ исчерпан. Он обновится в полночь по Москве. "
    "Чтобы продолжить сейчас, добавьте свой ключ в настройках"
)
# Время в details ошибки — как в остальном API: ISO 8601 UTC с «Z».
_DATETIME = TypeAdapter(datetime)


class KeyVerdict(StrEnum):
    """Что ответил провайдер на пробный запрос с ключом студента."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NO_FUNDS = "no_funds"
    UNAVAILABLE = "unavailable"


# Пробный запрос к провайдеру: в API — check_key, в тестах — он же с моком httpx.
KeyCheck = Callable[[LLMProviderSettings, SecretStr], Awaitable[KeyVerdict]]


def _cipher(settings: Settings) -> MultiFernet | None:
    """Шифр из APP_ENCRYPTION_KEY: первый ключ шифрует, все расшифровывают."""
    keys = settings.encryption_keys
    return MultiFernet([Fernet(key) for key in keys]) if keys else None


def _format_problem(key: str) -> str | None:
    if not KEY_MIN_LENGTH <= len(key) <= KEY_MAX_LENGTH:
        return KEY_LENGTH_MESSAGE
    if KEY_PATTERN.fullmatch(key) is None:
        return KEY_FORMAT_MESSAGE
    return None


async def check_key(
    provider: LLMProviderSettings,
    key: SecretStr,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> KeyVerdict:
    """Пробный запрос к основной модели провайдера: ответ в 1 токен за счёт ключа студента.

    Адрес — из настроек сервиса, а не от студента: сервер не отправит запрос куда-то ещё.
    Ключ уходит только в заголовке Authorization; в лог — статус ответа или тип сбоя.
    Ключ отклонён (401, 403) или нет денег (402) — так и отвечаем. Нет ответа за
    KEY_CHECK_TIMEOUT_S или 5xx — проверить не вышло. Другой ответ (429 — провайдер
    перегружен, 400 — ему не понравился запрос) — ключ он принял.
    """
    url = str(provider.base_url).rstrip("/") + "/chat/completions"
    body = {
        "model": provider.models["main"].name,
        "messages": [{"role": "user", "content": "Ответь одним словом: да"}],
        "max_tokens": 1,
    }
    headers = {"Authorization": f"Bearer {key.get_secret_value()}"}
    try:
        async with (
            asyncio.timeout(KEY_CHECK_TIMEOUT_S),
            httpx.AsyncClient(transport=transport, timeout=KEY_CHECK_TIMEOUT_S) as client,
        ):
            response = await client.post(url, json=body, headers=headers)
    except (httpx.HTTPError, TimeoutError) as error:
        logger.warning("llm_key_check_failed", error_type=type(error).__name__)
        return KeyVerdict.UNAVAILABLE
    status = response.status_code
    logger.info("llm_key_checked", status=status)
    if status in (401, 403):
        return KeyVerdict.REJECTED
    if status == 402:
        return KeyVerdict.NO_FUNDS
    if status >= 500:
        return KeyVerdict.UNAVAILABLE
    return KeyVerdict.ACCEPTED


async def get_key(session: AsyncSession, user_id: uuid.UUID) -> LlmKey | None:
    return await session.get(LlmKey, user_id)


async def save_key(
    session: AsyncSession,
    user_id: uuid.UUID,
    raw_key: SecretStr,
    settings: Settings,
    check: KeyCheck,
) -> LlmKey:
    """Проверяет ключ у основного провайдера и сохраняет зашифрованным вместо прежнего.
    Коммитит.

    Не настроены ИИ или шифрование — 500. Неверный формат или провайдер отклонил ключ —
    422 по полю key. Провайдер не ответил — 500, ключ не сохраняется.
    """
    provider = settings.llm_default_provider
    if provider is None:
        raise AppError(ErrorCode.INTERNAL, LLM_NOT_CONFIGURED_MESSAGE, 500)
    cipher = _cipher(settings)
    if cipher is None:
        logger.error("llm_key_encryption_missing")
        raise AppError(ErrorCode.INTERNAL, ENCRYPTION_MISSING_MESSAGE, 500)
    key = raw_key.get_secret_value().strip()
    problem = _format_problem(key)
    if problem is not None:
        raise request_error(["body", "key"], problem)
    # Соединение с базой не держим, пока ждём провайдера: до KEY_CHECK_TIMEOUT_S.
    await session.commit()
    verdict = await check(settings.llm_providers[provider], SecretStr(key))
    if verdict is KeyVerdict.REJECTED:
        raise request_error(["body", "key"], KEY_REJECTED_MESSAGE)
    if verdict is KeyVerdict.NO_FUNDS:
        raise request_error(["body", "key"], KEY_NO_FUNDS_MESSAGE)
    if verdict is KeyVerdict.UNAVAILABLE:
        raise AppError(ErrorCode.INTERNAL, KEY_UNAVAILABLE_MESSAGE, 500)
    values = {
        "provider": provider,
        "encrypted_key": cipher.encrypt(key.encode()).decode(),
        "last4": key[-4:],
    }
    statement = (
        insert(LlmKey)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=[LlmKey.user_id], set_={**values, "created_at": func.now()}
        )
        .returning(LlmKey)
    )
    saved = await session.scalar(statement, execution_options={"populate_existing": True})
    if saved is None:
        raise RuntimeError("INSERT … RETURNING не вернул строку ключа")
    await session.commit()
    logger.info("llm_key_saved", user_id=str(user_id), provider=provider)
    return saved


async def delete_key(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Удаляет свой ключ, если он был. Коммитит."""
    deleted = await session.scalar(
        delete(LlmKey).where(LlmKey.user_id == user_id).returning(LlmKey.user_id)
    )
    await session.commit()
    if deleted is not None:
        logger.info("llm_key_deleted", user_id=str(user_id))


async def usable_key(
    session: AsyncSession, user_id: uuid.UUID, settings: Settings
) -> SecretStr | None:
    """Свой ключ студента для прогона или описания картинки; None — работать на ключе сервиса.

    Ключа нет, он сохранён для другого провайдера (основной сменили), шифрование не
    настроено или ключ не расшифровался (ключ шифрования убрали раньше времени) — None.
    """
    row = await get_key(session, user_id)
    if row is None or row.provider != settings.llm_default_provider:
        return None
    cipher = _cipher(settings)
    if cipher is None:
        logger.warning("llm_key_encryption_missing", user_id=str(user_id))
        return None
    try:
        return SecretStr(cipher.decrypt(row.encrypted_key.encode()).decode())
    except InvalidToken:
        logger.warning("llm_key_undecryptable", user_id=str(user_id))
        return None


async def rotate_keys(session: AsyncSession, settings: Settings) -> tuple[int, int]:
    """Перешифровывает все ключи первым ключом из APP_ENCRYPTION_KEY. Коммитит.

    После этого старые ключи шифрования можно убрать. Возвращает (перешифровано, не
    расшифровалось): такие ключи студентам придётся сохранить заново.
    """
    cipher = _cipher(settings)
    if cipher is None:
        raise RuntimeError("APP_ENCRYPTION_KEY не задан")
    rotated = broken = 0
    for row in await session.scalars(select(LlmKey).with_for_update()):
        try:
            row.encrypted_key = cipher.rotate(row.encrypted_key.encode()).decode()
        except InvalidToken:
            logger.warning("llm_key_undecryptable", user_id=str(row.user_id))
            broken += 1
            continue
        rotated += 1
    await session.commit()
    return rotated, broken


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


def quota_resets_at(moment: ColumnElement[datetime] | datetime) -> ColumnElement[datetime]:
    """Когда начнётся следующий день квоты: ближайшая полночь по Москве после момента."""
    midnight = cast(quota_day(moment) + 1, DateTime)
    return func.timezone(QUOTA_TIMEZONE, midnight, type_=DateTime(timezone=True))


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


@dataclass(frozen=True)
class Quota:
    """Квота студента на сегодня (9.1)."""

    tokens_used: int
    tokens_limit: int
    resets_at: datetime

    @property
    def exhausted(self) -> bool:
        return self.tokens_used >= self.tokens_limit


async def get_quota(session: AsyncSession, user_id: uuid.UUID, settings: Settings) -> Quota:
    """Сколько токенов студент потратил сегодня на ключе сервиса, лимит и время сброса."""
    today = quota_day(func.now())
    used = (
        select(Usage.tokens_in + Usage.tokens_out)
        .where(Usage.user_id == user_id, Usage.day == today)
        .scalar_subquery()
    )
    row = (await session.execute(select(func.coalesce(used, 0), quota_resets_at(func.now())))).one()
    return Quota(tokens_used=row[0], tokens_limit=settings.llm_daily_token_limit, resets_at=row[1])


async def ensure_quota(session: AsyncSession, user_id: uuid.UUID, settings: Settings) -> None:
    """Перед прогоном: со своим ключом квота не проверяется; лимит исчерпан — 429.

    Начатый прогон квота не обрывает, поэтому перерасход — не больше одного прогона
    (architecture.md 8).
    """
    if await usable_key(session, user_id, settings) is not None:
        return
    quota = await get_quota(session, user_id, settings)
    if quota.exhausted:
        logger.info("quota_exceeded", user_id=str(user_id), tokens_used=quota.tokens_used)
        raise AppError(
            ErrorCode.QUOTA_EXCEEDED,
            QUOTA_MESSAGE,
            429,
            {"resets_at": _DATETIME.dump_python(quota.resets_at, mode="json")},
        )
