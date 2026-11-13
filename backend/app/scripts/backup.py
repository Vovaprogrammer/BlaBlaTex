"""Бэкап базы и хранилища (docs/deploy.md): python -m app.scripts.backup [--daily ЧЧ:ММ].

Бэкап — папка <--dir>/<дата_время>: db.dump (pg_dump в своём формате) и storage/ — копия
хранилища. Дамп и файлы подходят друг к другу: пока идёт бэкап, уборка хранилища ничего не
удаляет (core/blob_locks.py), и blob из дампа не пропадёт, пока его копируют. Файлы,
загруженные во время бэкапа, попадут в копию без ссылок из дампа — после восстановления их
уберёт уборка.

Файл в хранилище не меняется: имя — sha256 содержимого. Поэтому то, что уже есть в прошлом
бэкапе, берётся оттуда жёсткой ссылкой: каждый бэкап полный, а место занимает только новое.
Хранятся последние --keep бэкапов.

Без --daily — один бэкап сейчас. С --daily 03:00 — каждый день в это время по Москве, пока
работает процесс: так его запускает сервис backup в deploy/compose.server.yaml.
"""

import argparse
import asyncio
import os
import re
import shutil
import sys
import time as clock
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from app.core import blob_locks
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.core.logging import configure_logging

logger = structlog.get_logger(__name__)

BACKUP_DIR = Path("/srv/backups")
DEFAULT_KEEP = 14
MOSCOW = ZoneInfo("Europe/Moscow")
DUMP_NAME = "db.dump"
STORAGE_NAME = "storage"
# Имя папки бэкапа: по нему же бэкапы сортируются по времени. Два бэкапа в одну секунду
# (ночной и ручной) — второй с номером: 2026-11-13_030000-2.
NAME_FORMAT = "%Y-%m-%d_%H%M%S"
NAME_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}_\d{6}(?:-\d+)?")
# Папка бэкапа, который ещё идёт: с точки, поэтому среди готовых её нет.
PARTIAL_PREFIX = ".partial-"
# Недоделанный бэкап старше этого — остаток упавшего запуска, а не идущий сейчас.
STALE_PARTIAL = timedelta(days=1)
# Недописанные загрузки в корне хранилища (core/storage.py) — не файлы студентов.
STORAGE_TEMP_PREFIX = ".tmp-"


class PgError(Exception):
    """pg_dump или pg_restore завершился с ошибкой."""


def pg_env(settings: Settings) -> dict[str, str]:
    """Окружение для pg_dump и pg_restore. Пароль — переменной, а не в командной строке:
    её видно в списке процессов."""
    return {
        "PGHOST": settings.postgres_host,
        "PGPORT": str(settings.postgres_port),
        "PGUSER": settings.postgres_user,
        "PGDATABASE": settings.postgres_db,
        "PGPASSWORD": settings.postgres_password.get_secret_value(),
    }


async def run_pg(program: str, *args: str, settings: Settings) -> None:
    """Запускает pg_dump или pg_restore; ненулевой код → PgError с концом его вывода."""
    process = await asyncio.create_subprocess_exec(
        program,
        *args,
        env=pg_env(settings),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise PgError(f"{program}: {stderr.decode(errors='replace').strip()[-2000:]}")


def copy_storage(source: Path, target: Path, previous: Path | None = None) -> int:
    """Копирует файлы хранилища из source в target → сколько скопировано.

    Файлы, которые в target уже есть, не трогает. Тот же файл из previous (прошлого бэкапа)
    берёт жёсткой ссылкой, а не копией."""
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name.startswith(STORAGE_TEMP_PREFIX):
            continue
        relative = path.relative_to(source)
        destination = target / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        known = previous / relative if previous is not None else None
        if known is not None and known.is_file() and known.stat().st_size == path.stat().st_size:
            try:
                os.link(known, destination)
                copied += 1
                continue
            # Другая файловая система или ссылки не поддерживаются — тогда просто копия.
            except OSError:
                pass
        shutil.copy2(path, destination)
        copied += 1
    return copied


def finished_backups(root: Path) -> list[Path]:
    """Готовые бэкапы в root, от старых к новым. Только папки с именем бэкапа: в папке для
    бэкапов на сервере бывает и чужое (lost+found), а старые бэкапы отсюда удаляются."""
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and NAME_PATTERN.fullmatch(path.name)
    )


def prune(root: Path, keep: int) -> list[Path]:
    """Удаляет старые бэкапы, кроме последних keep, и остатки упавших запусков →
    удалённые готовые бэкапы."""
    backups = finished_backups(root)
    removed = backups[: max(len(backups) - keep, 0)]
    for path in removed:
        shutil.rmtree(path)
    stale_before = clock.time() - STALE_PARTIAL.total_seconds()
    for path in root.glob(f"{PARTIAL_PREFIX}*"):
        if path.stat().st_mtime < stale_before:
            shutil.rmtree(path, ignore_errors=True)
    return removed


def start_backup(root: Path, stamp: str) -> tuple[Path, str, Path | None]:
    """Создаёт папку нового бэкапа → (она, имя готового бэкапа, хранилище прошлого или None)."""
    root.mkdir(parents=True, exist_ok=True)
    backups = finished_backups(root)
    previous = backups[-1] / STORAGE_NAME if backups else None
    number = 1
    while True:
        name = stamp if number == 1 else f"{stamp}-{number}"
        partial = root / f"{PARTIAL_PREFIX}{name}"
        if not (root / name).exists():
            try:
                partial.mkdir()
                return partial, name, previous
            # Эту же секунду уже занял другой бэкап, который ещё идёт.
            except FileExistsError:
                pass
        number += 1


async def backup(settings: Settings, root: Path, keep: int, now: datetime | None = None) -> Path:
    """Один бэкап в root → его папка. Потом удаляет бэкапы старше последних keep."""
    stamp = (now or datetime.now(MOSCOW)).strftime(NAME_FORMAT)
    partial, name, previous = await asyncio.to_thread(start_backup, root, stamp)
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection, blob_locks.deletes_paused(connection):
            # Замок — на соединение и переживает commit, а открытая транзакция не висит
            # всё время бэкапа.
            await connection.commit()
            await run_pg(
                "pg_dump", "--format=custom", f"--file={partial / DUMP_NAME}", settings=settings
            )
            files = await asyncio.to_thread(
                copy_storage, settings.storage_dir, partial / STORAGE_NAME, previous
            )
    except BaseException:
        await asyncio.to_thread(shutil.rmtree, partial, ignore_errors=True)
        raise
    finally:
        await engine.dispose()
    final = await asyncio.to_thread(partial.rename, root / name)
    removed = await asyncio.to_thread(prune, root, keep)
    logger.info("backup_done", backup=name, files=files, removed=len(removed))
    return final


def seconds_until(at: time, now: datetime) -> float:
    """Сколько секунд от now до ближайших at часов того же пояса: сегодня или завтра."""
    target = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily(settings: Settings, root: Path, keep: int, at: time) -> None:
    """Бэкап каждый день в at по Москве. Сбой одного бэкапа не останавливает следующие."""
    logger.info("backup_scheduled", at=at.isoformat(timespec="minutes"), timezone=MOSCOW.key)
    last_day = None
    while True:
        await asyncio.sleep(seconds_until(at, datetime.now(MOSCOW)))
        # Сон отмеряют монотонные часы, а время — настенные. Если их подвели назад, проснулись
        # чуть раньше at: второй бэкап за тот же день не нужен, ждём следующего.
        today = datetime.now(MOSCOW).date()
        if today == last_day:
            await asyncio.sleep(1)
            continue
        last_day = today
        try:
            await backup(settings, root, keep)
        # Exception: любой сбой базы, pg_dump или диска — повод попробовать завтра.
        except Exception:
            logger.exception("backup_failed")


def day_time(value: str) -> time:
    """Время дня из «ЧЧ:ММ» или «Ч:ММ»: 03:00 и 3:00 — одно и то же."""
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"время бэкапа — ЧЧ:ММ, например 03:00, а не {value!r}"
        ) from None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.backup", description="Бэкап базы и файлов BlaBlaTex"
    )
    parser.add_argument("--dir", type=Path, default=BACKUP_DIR, help="куда класть бэкапы")
    parser.add_argument(
        "--keep", type=int, default=DEFAULT_KEEP, help="сколько последних бэкапов хранить"
    )
    parser.add_argument(
        "--daily",
        type=day_time,
        metavar="ЧЧ:ММ",
        help="делать бэкап каждый день в это время по Москве",
    )
    args = parser.parse_args(argv)
    if args.keep < 1:
        parser.error("--keep: хотя бы 1")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    settings = get_settings()
    # Свои настройки логов: трейсбек без локальных переменных, в них есть пароль базы.
    configure_logging(settings)
    if args.daily is not None:
        asyncio.run(run_daily(settings, args.dir, args.keep, args.daily))
        return 0
    try:
        asyncio.run(backup(settings, args.dir, args.keep))
    except PgError as error:
        logger.error("backup_failed", reason=str(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
