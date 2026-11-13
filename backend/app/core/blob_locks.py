"""Замок Postgres на blob хранилища (architecture.md 5, «Уборка хранилища»).

Одинаковый файл двух студентов лежит в Storage один раз, и уборка удаляет blob, только
когда на него больше никто не ссылается. Загрузка и сборка сначала кладут blob и лишь потом
записывают на него ссылку — в этот промежуток уборка не должна его удалить. Поэтому обе
стороны берут advisory lock на sha256 до конца своей транзакции: уборка — эксклюзивный,
пока проверяет ссылки и удаляет, запись — на чтение, пока не закоммитит ссылку.

Бэкап (app/scripts/backup.py) сначала снимает дамп базы, потом копирует файлы. Если бы blob,
на который ссылается дамп, удалили между этими шагами, бэкап не подошёл бы к самому себе.
Поэтому на время бэкапа удаление выключено: он держит эксклюзивный замок BACKUP_LOCK, а
удаление сначала пробует взять его на чтение и, если не вышло, откладывает blob до следующей
уборки.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.storage import Storage


def lock_key(sha256: str) -> int:
    """Ключ замка: первые 64 бита хеша как bigint со знаком. Если ключи двух blob'ов
    совпадут, одна сторона просто подождёт другую."""
    return int.from_bytes(bytes.fromhex(sha256[:16]), "big", signed=True)


# Замок бэкапа. Ключ из двух int4: такие замки не пересекаются с замками blob'ов из одного
# bigint, даже если число совпадёт. 0x42425442 — «BBTB».
BACKUP_LOCK = (0x42425442, 1)


async def lock_for_delete(session: AsyncSession, sha256: str) -> bool:
    """Эксклюзивный замок до конца транзакции: ждёт, пока запись с этим blob закоммитит
    ссылку, и не даёт новой записи начаться, пока уборка не закончит.

    False — идёт бэкап, и удалять сейчас нельзя: blob уберёт следующая уборка. Бэкап не ждём,
    он идёт минуты, а удаление аккаунта ждёт уборку в запросе студента."""
    if not await session.scalar(select(func.pg_try_advisory_xact_lock_shared(*BACKUP_LOCK))):
        return False
    await session.execute(select(func.pg_advisory_xact_lock(lock_key(sha256))))
    return True


@asynccontextmanager
async def deletes_paused(connection: AsyncConnection) -> AsyncIterator[None]:
    """Пока открыт, ни один blob не удаляется. Сначала ждёт удаления, которые уже идут.

    Замок — на соединение, а не на транзакцию: дамп базы снимает отдельный процесс pg_dump,
    своей транзакции у бэкапа нет."""
    await connection.execute(select(func.pg_advisory_lock(*BACKUP_LOCK)))
    try:
        yield
    finally:
        await connection.execute(select(func.pg_advisory_unlock(*BACKUP_LOCK)))


async def put_held(session: AsyncSession, storage: Storage, data: bytes | BinaryIO) -> str:
    """Кладёт blob и держит на нём замок записи до конца транзакции; возвращает sha256.

    Ссылку на blob вызывающий записывает в этой же транзакции. Если уборка удалила такой
    же blob между записью и замком, он кладётся снова: после замка уборка его уже не тронет.
    """
    sha256 = await _put(storage, data)
    # Без autoflush: вызывающий мог уже начать строку со ссылкой, но ещё её не дописал.
    with session.no_autoflush:
        await session.execute(select(func.pg_advisory_xact_lock_shared(lock_key(sha256))))
    if not await storage.exists(sha256):
        await _put(storage, data)
    return sha256


async def _put(storage: Storage, data: bytes | BinaryIO) -> str:
    if isinstance(data, bytes):
        return await storage.put(data)
    return await storage.put_file(data)
