"""Схемы своего ключа LLM и квоты (architecture.md 9.1)."""

from datetime import datetime

from pydantic import BaseModel, Field, SecretStr


class LlmKeySave(BaseModel):
    # SecretStr: ключ не попадает в repr, логи и ошибки проверки.
    key: SecretStr = Field(
        description=(
            "Ключ аккаунта у провайдера: 8–500 видимых символов ASCII без пробелов, "
            "пробелы по краям обрезаются"
        )
    )


class LlmKeyOut(BaseModel):
    provider: str = Field(description="Провайдер из LLM_PROVIDERS, для которого сохранён ключ")
    last4: str = Field(description="Последние 4 символа ключа: сам ключ наружу не отдаётся")
    created_at: datetime


class LlmKeySettings(BaseModel):
    provider: str | None = Field(
        description=(
            "Для какого провайдера нужен ключ (основной провайдер сервиса); "
            "null — ИИ на сервере не настроен"
        )
    )
    key: LlmKeyOut | None = Field(
        description=(
            "Сохранённый ключ или null. Его provider не совпадает с provider выше — "
            "ключ сохранён для прежнего провайдера и не используется"
        )
    )


class UsageOut(BaseModel):
    tokens_used: int = Field(
        description=(
            "Токены (вход и выход), потраченные сегодня на ключе сервиса. Может быть больше "
            "tokens_limit: начатый прогон квота не обрывает"
        )
    )
    tokens_limit: int = Field(description="Дневной лимит токенов")
    resets_at: datetime = Field(description="Когда начнётся новый день: полночь по Москве, в UTC")
    own_key: bool = Field(description="Работает свой ключ: квота не расходуется")
