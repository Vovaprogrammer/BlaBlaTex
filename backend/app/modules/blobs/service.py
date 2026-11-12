"""Уборка хранилища (architecture.md 5, «Уборка хранилища»).

Одинаковые файлы лежат в Storage один раз, даже у разных студентов, поэтому blob удаляется,
только если на него не ссылается ни файл, ни ревизия, ни сборка — ни в одном проекте.
Ссылки знают модули-владельцы таблиц: projects (файлы, ревизии) и builds (сборки).

Каждый blob удаляется в своей короткой транзакции под эксклюзивным замком
(core/blob_locks.py): загрузка или сборка, которая кладёт такой же blob, либо успеет
записать ссылку раньше — и blob останется, — либо дождётся конца уборки и положит его снова.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import blob_locks
from app.core.storage import Storage
from app.modules.builds import service as builds_service
from app.modules.projects import service as projects_service

logger = structlog.get_logger(__name__)

# Ночная уборка не трогает blob'ы моложе этого: запас для записи, которая ещё не дошла
# до ссылки, — на случай, если какой-то путь записи обходит замок.
MIN_AGE = timedelta(hours=1)
# Сколько blob'ов ночная уборка проверяет одним запросом.
SWEEP_BATCH = 500


@dataclass
class Cleanup:
    """Итог уборки: сколько blob'ов удалено, сколько оставлено из-за чужих ссылок и сколько
    не удалось удалить (их повторит ночная уборка)."""

    deleted: int = 0
    kept: int = 0
    failed: int = 0

    def add(self, other: "Cleanup") -> None:
        self.deleted += other.deleted
        self.kept += other.kept
        self.failed += other.failed


async def referenced(session: AsyncSession, sha256s: Collection[str]) -> set[str]:
    """Какие из sha256 упомянуты в файлах, ревизиях или сборках любого проекта."""
    in_projects = await projects_service.referenced_blobs(session, sha256s)
    in_builds = await builds_service.referenced_blobs(session, sha256s)
    return in_projects | in_builds


async def delete_unreferenced(
    session: AsyncSession, storage: Storage, sha256s: Collection[str]
) -> Cleanup:
    """Удаляет blob'ы, на которые никто не ссылается. Коммитит сессию после каждого blob.

    Сбой на одном blob не останавливает остальные: уборка — не условие того, ради чего
    её вызвали (удаления аккаунта), а оставшийся ничьим blob уберёт ночная уборка.
    """
    result = Cleanup()
    for sha256 in sorted(sha256s):
        try:
            await blob_locks.lock_for_delete(session, sha256)
            if await referenced(session, [sha256]):
                result.kept += 1
            else:
                await storage.delete(sha256)
                result.deleted += 1
            await session.commit()
        # Exception: любой сбой диска или базы на одном blob — повод перейти к следующему.
        except Exception as error:
            await session.rollback()
            result.failed += 1
            # Без sha256: по хешу можно узнать, что за файл был у студента.
            logger.warning("blob_cleanup_failed", reason=repr(error))
    return result


async def sweep(session: AsyncSession, storage: Storage) -> Cleanup:
    """Ночная уборка: удаляет blob'ы старше MIN_AGE, на которые никто не ссылается.

    Так уходят blob'ы удалённых проектов, неудачных загрузок и аккаунтов, чья уборка
    оборвалась. Коммитит сессию."""
    candidates = await storage.list_older_than(MIN_AGE)
    result = Cleanup()
    for start in range(0, len(candidates), SWEEP_BATCH):
        batch = candidates[start : start + SWEEP_BATCH]
        unreferenced = set(batch) - await referenced(session, batch)
        await session.commit()
        # Ссылки перепроверяются под замком: между запросами их могли записать.
        result.add(await delete_unreferenced(session, storage, unreferenced))
    return result
