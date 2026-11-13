"""Скрипты установки из готовых образов: секреты, бэкап и восстановление (docs/deploy.md)."""

import asyncio
import os
import time
from datetime import datetime, timedelta
from datetime import time as day_time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core import blob_locks
from app.core.config import Settings
from app.scripts import backup as backup_script
from app.scripts.backup import (
    MOSCOW,
    PARTIAL_PREFIX,
    copy_storage,
    finished_backups,
    prune,
    seconds_until,
)
from app.scripts.init_secrets import ensure_secrets
from app.scripts.restore import RestoreError, restore
from tests.live_builds import Live

DATA = b"%PDF-1.7 backup sample"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переменные окружения разработчика не должны перекрыть секреты из файлов."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


# Секреты.


def test_secrets_are_created_once(tmp_path: Path) -> None:
    created = ensure_secrets(tmp_path)
    password = (tmp_path / "postgres_password").read_text(encoding="ascii")
    key = (tmp_path / "app_encryption_key").read_text(encoding="ascii")

    again = ensure_secrets(tmp_path)

    assert created == ["postgres_password", "app_encryption_key"]
    # Повторный запуск не меняет пароль базы и ключ: иначе база и ключи студентов не открылись бы.
    assert again == []
    assert (tmp_path / "postgres_password").read_text(encoding="ascii") == password
    assert (tmp_path / "app_encryption_key").read_text(encoding="ascii") == key
    assert len(password) >= 40
    Fernet(key)


def test_empty_secret_is_created_again(tmp_path: Path) -> None:
    ensure_secrets(tmp_path)
    # Файл секрета только для чтения, а на Windows такой не удалить.
    (tmp_path / "postgres_password").chmod(0o644)
    (tmp_path / "postgres_password").write_text("", encoding="ascii")

    assert ensure_secrets(tmp_path) == ["postgres_password"]
    assert (tmp_path / "postgres_password").read_text(encoding="ascii")
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.usefixtures("clean_env")
def test_settings_read_secrets_from_files(tmp_path: Path) -> None:
    ensure_secrets(tmp_path)

    settings = Settings(_env_file=None, _secrets_dir=tmp_path)

    password = (tmp_path / "postgres_password").read_text(encoding="ascii")
    assert settings.postgres_password.get_secret_value() == password
    assert len(settings.encryption_keys) == 1


@pytest.mark.usefixtures("clean_env")
def test_environment_wins_over_secret_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_secrets(tmp_path)
    old_key = (tmp_path / "app_encryption_key").read_text(encoding="ascii")
    new_key = Fernet.generate_key().decode()
    # Так меняют ключ шифрования (docs/deploy.md): новый и старый — через переменную.
    monkeypatch.setenv("APP_ENCRYPTION_KEY", f"{new_key},{old_key}")

    settings = Settings(_env_file=None, _secrets_dir=tmp_path)

    assert settings.encryption_keys == [new_key, old_key]


# Копия хранилища и старые бэкапы.


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_copy_storage_links_known_files_and_skips_unfinished(tmp_path: Path) -> None:
    source, previous, target = tmp_path / "storage", tmp_path / "old", tmp_path / "new"
    write(source / "ab" / "cd" / "abcd1", b"old file")
    write(source / "ef" / "01" / "ef012", b"new file")
    write(source / ".tmp-upload", b"half")
    write(previous / "ab" / "cd" / "abcd1", b"old file")

    copied = copy_storage(source, target, previous)

    assert copied == 2
    assert (target / "ef" / "01" / "ef012").read_bytes() == b"new file"
    # Тот же файл из прошлого бэкапа — жёсткой ссылкой: места он больше не занимает.
    assert (
        os.stat(target / "ab" / "cd" / "abcd1").st_ino
        == os.stat(previous / "ab" / "cd" / "abcd1").st_ino
    )
    assert not (target / ".tmp-upload").exists()


def test_copy_storage_keeps_existing_files(tmp_path: Path) -> None:
    source, target = tmp_path / "backup", tmp_path / "storage"
    write(source / "ab" / "cd" / "abcd1", b"from backup")
    write(target / "ab" / "cd" / "abcd1", b"already here")

    assert copy_storage(source, target) == 0
    assert (target / "ab" / "cd" / "abcd1").read_bytes() == b"already here"


def test_prune_keeps_latest_and_removes_stale_partials(tmp_path: Path) -> None:
    for name in ("2026-11-10_030000", "2026-11-11_030000", "2026-11-12_030000"):
        (tmp_path / name).mkdir()
    stale = tmp_path / f"{PARTIAL_PREFIX}2026-11-01_030000"
    running = tmp_path / f"{PARTIAL_PREFIX}2026-11-13_030000"
    stale.mkdir()
    running.mkdir()
    day_ago = time.time() - 2 * 24 * 60 * 60
    os.utime(stale, (day_ago, day_ago))

    removed = prune(tmp_path, keep=2)

    assert [path.name for path in removed] == ["2026-11-10_030000"]
    assert [path.name for path in finished_backups(tmp_path)] == [
        "2026-11-11_030000",
        "2026-11-12_030000",
    ]
    assert not stale.exists()
    # Бэкап, который идёт сейчас, не трогаем.
    assert running.exists()


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 11, 13, 2, 0, tzinfo=MOSCOW), timedelta(hours=1)),
        (datetime(2026, 11, 13, 3, 0, tzinfo=MOSCOW), timedelta(days=1)),
        (datetime(2026, 11, 13, 23, 30, tzinfo=MOSCOW), timedelta(hours=3, minutes=30)),
    ],
)
def test_daily_backup_waits_for_next_time(now: datetime, expected: timedelta) -> None:
    assert seconds_until(day_time(3, 0), now) == expected.total_seconds()


# Бэкап целиком: настоящий pg_dump есть только в образе, здесь — подмена.


async def test_backup_dumps_and_copies_while_deletion_is_paused(
    live: Live,
    db_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha256 = await live.storage.put(DATA)
    settings = db_settings.model_copy(update={"storage_dir": live.storage.root})
    deletions_during_dump: list[bool] = []

    async def fake_pg(program: str, *args: str, settings: Settings) -> None:
        async with live.sessionmaker() as cleaner:
            deletions_during_dump.append(await blob_locks.lock_for_delete(cleaner, sha256))
        [target] = [arg.removeprefix("--file=") for arg in args if arg.startswith("--file=")]
        await asyncio.to_thread(Path(target).write_bytes, b"dump")

    monkeypatch.setattr(backup_script, "run_pg", fake_pg)
    root = tmp_path / "backups"

    first = await backup_script.backup(
        settings, root, keep=5, now=datetime(2026, 11, 12, 3, 0, tzinfo=MOSCOW)
    )
    second = await backup_script.backup(
        settings, root, keep=5, now=datetime(2026, 11, 13, 3, 0, tzinfo=MOSCOW)
    )

    # Пока снимается дамп, удалить blob нельзя.
    assert deletions_during_dump == [False, False]
    relative = live.storage.path(sha256).relative_to(live.storage.root)
    assert (first / "db.dump").read_bytes() == b"dump"
    assert (first / "storage" / relative).read_bytes() == DATA
    assert (
        os.stat(second / "storage" / relative).st_ino
        == os.stat(first / "storage" / relative).st_ino
    )
    assert [path.name for path in root.iterdir()] == [first.name, second.name]
    # После бэкапа удаление снова работает.
    async with live.sessionmaker() as cleaner:
        assert await blob_locks.lock_for_delete(cleaner, sha256)
        await cleaner.rollback()


async def test_restore_refuses_folder_without_dump(db_settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(RestoreError, match="не папка бэкапа"):
        await restore(db_settings, tmp_path)


async def test_restore_refuses_database_with_tables(db_settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "db.dump").write_bytes(b"dump")

    # В тестовой базе уже есть таблицы: поверх них восстанавливать нельзя.
    with pytest.raises(RestoreError, match="База не пустая"):
        await restore(db_settings, tmp_path)
