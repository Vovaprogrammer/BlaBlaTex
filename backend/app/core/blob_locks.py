"""Замок Postgres на blob хранилища (architecture.md 5, «Уборка хранилища»).

Одинаковый файл двух студентов лежит в Storage один раз, и уборка удаляет blob, только
когда на него больше никто не ссылается. Загрузка и сборка сначала кладут blob и лишь потом
записывают на него ссылку — в этот промежуток уборка не должна его удалить. Поэтому обе
стороны берут advisory lock на sha256 до конца своей транзакции: уборка — эксклюзивный,
пока проверяет ссылки и удаляет, запись — на чтение, пока не закоммитит ссылку.
"""

from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage


def lock_key(sha256: str) -> int:
    """Ключ замка: первые 64 бита хеша как bigint со знаком. Если ключи двух blob'ов
    совпадут, одна сторона просто подождёт другую."""
    return int.from_bytes(bytes.fromhex(sha256[:16]), "big", signed=True)


async def lock_for_delete(session: AsyncSession, sha256: str) -> None:
    """Эксклюзивный замок до конца транзакции: ждёт, пока запись с этим blob закоммитит
    ссылку, и не даёт новой записи начаться, пока уборка не закончит."""
    await session.execute(select(func.pg_advisory_xact_lock(lock_key(sha256))))


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
