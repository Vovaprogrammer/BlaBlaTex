"""Зависимости роутов своего ключа: настройки приложения и пробный запрос к провайдеру."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.modules.llm import service


def get_app_settings(request: Request) -> Settings:
    """Настройки приложения: в тестах — настройки теста, а не .env разработчика."""
    settings: Settings = request.app.state.settings
    return settings


def get_key_check() -> service.KeyCheck:
    """Чем проверять ключ у провайдера; тесты подменяют его моком httpx."""
    return service.check_key


AppSettings = Annotated[Settings, Depends(get_app_settings)]
KeyChecker = Annotated[service.KeyCheck, Depends(get_key_check)]
