"""Восстановление из бэкапа (docs/deploy.md): python -m app.scripts.restore <папка бэкапа>.

Только в пустую базу — на чистую установку, до первого запуска API: сервис migrate создал бы
таблицы, и данные из бэкапа легли бы поверх чужой схемы. Порядок шагов — в docs/deploy.md.

Сначала база, одной транзакцией: если pg_restore упадёт, база останется пустой, а хранилище
нетронутым. Потом файлы; те, что в хранилище уже есть, не перезаписываются. Схему до текущей
версии доведёт migrate при следующем запуске.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import structlog
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.core.logging import configure_logging
from app.scripts.backup import DUMP_NAME, STORAGE_NAME, PgError, copy_storage, run_pg

logger = structlog.get_logger(__name__)


class RestoreError(Exception):
    """Восстановить нельзя: не та папка или база не пустая. Текст — что сделать."""


async def database_is_empty(settings: Settings) -> bool:
    """В базе нет ни одной таблицы."""
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            tables = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            )
    finally:
        await engine.dispose()
    return tables == 0


async def restore(settings: Settings, source: Path) -> int:
    """Восстанавливает базу и файлы из папки бэкапа → сколько файлов скопировано."""
    dump = source / DUMP_NAME
    if not dump.is_file():
        raise RestoreError(f"В {source} нет {DUMP_NAME}: это не папка бэкапа")
    if not await database_is_empty(settings):
        raise RestoreError(
            "База не пустая. Восстанавливать можно только на чистую установку, "
            "до первого запуска API: см. docs/deploy.md"
        )
    await run_pg(
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--single-transaction",
        f"--dbname={settings.postgres_db}",
        str(dump),
        settings=settings,
    )
    return await asyncio.to_thread(copy_storage, source / STORAGE_NAME, settings.storage_dir)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.restore", description="Восстановление BlaBlaTex из бэкапа"
    )
    parser.add_argument("source", type=Path, help="папка бэкапа, например /srv/backups/<дата>")
    args = parser.parse_args(argv)
    settings = get_settings()
    # Свои настройки логов: трейсбек без локальных переменных, в них есть пароль базы.
    configure_logging(settings)
    try:
        files = asyncio.run(restore(settings, args.source))
    except (RestoreError, PgError) as error:
        logger.error("restore_failed", reason=str(error))
        return 1
    logger.info("restore_done", backup=args.source.name, files=files)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
