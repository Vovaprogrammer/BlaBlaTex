"""Свой ключ LLM и расход за сегодня (architecture.md 9.1)."""

from fastapi import APIRouter, Request

from app.core.db import DbSession
from app.core.errors import not_implemented
from app.core.ratelimit import Limit, get_rate_limiter
from app.modules.auth.dependencies import BrowserUser, CurrentUser
from app.modules.llm import service
from app.modules.llm.dependencies import AppSettings, KeyChecker
from app.modules.llm.models import LlmKey
from app.modules.llm.schemas import LlmKeyOut, LlmKeySave, LlmKeySettings, UsageOut

router = APIRouter(tags=["llm"])

# Каждая попытка сохранить ключ — запрос к провайдеру: сервер не должен стать проверялкой
# чужих ключей.
LLM_KEY_SAVE_LIMIT = Limit(count=10, period_s=3600)


def _key_out(key: LlmKey) -> LlmKeyOut:
    return LlmKeyOut(provider=key.provider, last4=key.last4, created_at=key.created_at)


@router.get("/settings/llm-key")
async def get_llm_key(
    user: BrowserUser, session: DbSession, settings: AppSettings
) -> LlmKeySettings:
    """Для какого провайдера нужен ключ и какой сохранён: только последние 4 символа."""
    key = await service.get_key(session, user.id)
    return LlmKeySettings(
        provider=settings.llm_default_provider, key=None if key is None else _key_out(key)
    )


@router.put("/settings/llm-key")
async def save_llm_key(
    body: LlmKeySave,
    user: BrowserUser,
    session: DbSession,
    settings: AppSettings,
    check: KeyChecker,
    request: Request,
) -> LlmKeyOut:
    """Проверяет ключ запросом к провайдеру и сохраняет зашифрованным вместо прежнего."""
    await get_rate_limiter(request).check("llm_key_save", str(user.id), LLM_KEY_SAVE_LIMIT)
    saved = await service.save_key(session, user.id, body.key, settings, check)
    return _key_out(saved)


@router.delete("/settings/llm-key", status_code=204)
async def delete_llm_key(user: BrowserUser, session: DbSession) -> None:
    """Удаляет свой ключ: работа снова идёт на ключе сервиса и в квоту."""
    await service.delete_key(session, user.id)


@router.get("/usage")
async def get_usage(user: CurrentUser) -> UsageOut:
    """Сколько токенов потрачено сегодня, дневной лимит и когда он обновится."""
    raise not_implemented()
