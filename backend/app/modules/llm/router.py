"""Свой ключ LLM и расход за сегодня (architecture.md 9.1)."""

from fastapi import APIRouter

from app.core.errors import not_implemented
from app.modules.auth.dependencies import BrowserUser, CurrentUser
from app.modules.llm.schemas import LlmKeyOut, LlmKeySave, LlmKeySettings, UsageOut

router = APIRouter(tags=["llm"])


@router.get("/settings/llm-key")
async def get_llm_key(user: BrowserUser) -> LlmKeySettings:
    """Для какого провайдера нужен ключ и какой сохранён: только последние 4 символа."""
    raise not_implemented()


@router.put("/settings/llm-key")
async def save_llm_key(body: LlmKeySave, user: BrowserUser) -> LlmKeyOut:
    """Проверяет ключ запросом к провайдеру и сохраняет зашифрованным вместо прежнего."""
    raise not_implemented()


@router.delete("/settings/llm-key", status_code=204)
async def delete_llm_key(user: BrowserUser) -> None:
    """Удаляет свой ключ: работа снова идёт на ключе сервиса и в квоту."""
    raise not_implemented()


@router.get("/usage")
async def get_usage(user: CurrentUser) -> UsageOut:
    """Сколько токенов потрачено сегодня, дневной лимит и когда он обновится."""
    raise not_implemented()
