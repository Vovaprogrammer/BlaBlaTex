"""Секреты установки из готовых образов (deploy/compose.yaml, docs/install.md).

Сервис init запускает это перед остальными: пароль базы и ключ шифрования своих ключей LLM
студентов создаются при первом запуске и лежат в отдельном томе Docker, рядом с данными.
Студенту ничего вписывать не нужно, а удалить всё вместе с данными — одна команда.

Повторный запуск ничего не меняет: с новым паролем не открылась бы уже созданная база, а с
новым ключом не расшифровались бы сохранённые ключи студентов.

Файлы читают бэкенд (настройки из SECRETS_DIR) и Postgres (POSTGRES_PASSWORD_FILE) — от разных
пользователей, поэтому файлы открыты на чтение всем. Том подключён только к контейнерам
BlaBlaTex, а у компилятора и сайта его нет.
"""

import os
import secrets
import sys
from collections.abc import Callable
from pathlib import Path

import structlog
from cryptography.fernet import Fernet

from app.core.config import SECRETS_DIR

logger = structlog.get_logger(__name__)

# Имя файла — имя настройки в app/core/config.py.
GENERATORS: dict[str, Callable[[], str]] = {
    "postgres_password": lambda: secrets.token_urlsafe(32),
    "app_encryption_key": lambda: Fernet.generate_key().decode(),
}


def ensure_secrets(directory: Path) -> list[str]:
    """Создаёт недостающие секреты → имена созданных. Существующие не трогает.

    Пустой файл считается недостающим: так бывает, только если прошлый запуск оборвался
    до записи, а с пустым паролем Postgres и не запустился бы.
    """
    created = []
    for name, generate in GENERATORS.items():
        path = directory / name
        if path.is_file() and path.read_text(encoding="ascii").strip():
            continue
        # Через временный файл: оборванная запись не оставит полсекрета под настоящим именем.
        temporary = directory / f".{name}.tmp"
        temporary.unlink(missing_ok=True)
        temporary.write_text(generate(), encoding="ascii")
        temporary.chmod(0o444)
        os.replace(temporary, path)
        created.append(name)
    return created


def main() -> int:
    created = ensure_secrets(SECRETS_DIR)
    # Только имена: значения секретов в лог не попадают.
    logger.info("secrets_ready", created=created)
    return 0


if __name__ == "__main__":
    sys.exit(main())
