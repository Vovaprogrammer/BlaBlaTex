"""Смена ключа шифрования своих ключей LLM студентов (architecture.md 5, 9.1).

1. В APP_ENCRYPTION_KEY новый ключ — первым через запятую: «новый,старый». Перезапустить API
   и воркер: новые ключи студентов уже шифруются новым, старые ещё читаются старым.
2. uv run python -m app.scripts.rotate_llm_keys — перешифровать все сохранённые ключи новым.
3. Убрать старый ключ из APP_ENCRYPTION_KEY и снова перезапустить.

Ключи, которые не расшифровал ни один ключ из списка, остаются как есть (их студентам придётся
сохранить заново); тогда скрипт завершается с кодом 1.
"""

import asyncio
import sys

import structlog

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.modules.llm import service

logger = structlog.get_logger(__name__)


async def rotate(settings: Settings) -> tuple[int, int]:
    """Перешифровывает ключи первым ключом шифрования → (перешифровано, не расшифровалось)."""
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            return await service.rotate_keys(session, settings)
    finally:
        await engine.dispose()


def main() -> int:
    settings = get_settings()
    if not settings.encryption_keys:
        logger.error("llm_keys_rotation_impossible", reason="APP_ENCRYPTION_KEY не задан")
        return 1
    rotated, undecryptable = asyncio.run(rotate(settings))
    logger.info("llm_keys_rotated", rotated=rotated, undecryptable=undecryptable)
    return 1 if undecryptable else 0


if __name__ == "__main__":
    sys.exit(main())
