"""Экспорт проекта архивом (architecture.md 9.1, «Экспорт»): исходники, которые собираются
и вне BlaBlaTex — в Overleaf, TeX Live, MiKTeX.

Проект — до 200 МБ, поэтому архив пишется во временный файл на диске, а не в память:
тексты приходят из базы пачками, картинки и документы — из Storage кусками. Сжатие
и запись идут в потоках, цикл событий их не ждёт. Без FastAPI: маршрут — в router.py.
"""

import asyncio
import os
import tempfile
import unicodedata
import zipfile
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from datetime import datetime
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import INTERNAL_MESSAGE, AppError, ErrorCode
from app.core.storage import BlobNotFoundError, Storage
from app.modules.projects import service
from app.modules.projects.models import Project
from app.modules.projects.service import ExportEntry

logger = structlog.get_logger(__name__)

# Папка общего класса в папке шаблонов: компилятор подключает её через TEXINPUTS (раздел 6).
SHARED_DIR_NAME = "_shared"
HOWTO_NAME = "Как собрать.txt"
_HOWTO_TEMPLATE = Path(__file__).with_name("export_howto.txt")
# Уже сжаты — картинки, PDF и документы Office (это тоже zip): сжимать их снова — только
# тратить процессор.
STORED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".pdf", ".docx", ".pptx", ".xlsx")
# Время в zip — местное, без часового пояса. Студенты — в Москве, как и день квоты (раздел 5).
MOSCOW = ZoneInfo("Europe/Moscow")
# Самая ранняя дата, которую умеет записать zip.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
# Unix: права файла и папки — в старших 16 битах external_attr, 0x10 — признак папки MS-DOS.
_UNIX = 3
_FILE_ATTR = 0o100644 << 16
_FOLDER_ATTR = (0o40755 << 16) | 0x10
READ_CHUNK = 1024 * 1024


async def build_archive(
    session: AsyncSession,
    storage: Storage,
    project: Project,
    *,
    shared_dir: Path,
    with_materials: bool,
) -> tuple[IO[bytes], int]:
    """Собирает zip проекта во временный файл и возвращает его, открытым с начала, и размер.

    Файл удаляется, когда его закрывают (read_archive закрывает сам, дочитав). Транзакцию
    сессии функция завершает сама, как только прочитала файлы проекта: соединение с базой
    не занято, пока пишутся картинки и идёт ответ.
    """
    out = await asyncio.to_thread(tempfile.TemporaryFile)
    try:
        await _write_archive(
            session, storage, project, out, shared_dir=shared_dir, with_materials=with_materials
        )
        size = await asyncio.to_thread(out.seek, 0, os.SEEK_END)
        await asyncio.to_thread(out.seek, 0)
    except BaseException:
        await asyncio.to_thread(out.close)
        raise
    return out, size


async def read_archive(file: IO[bytes]) -> AsyncIterator[bytes]:
    """Архив кусками для ответа; дочитав или при обрыве — закрывает и тем удаляет файл."""
    try:
        while chunk := await asyncio.to_thread(file.read, READ_CHUNK):
            yield chunk
    finally:
        await asyncio.to_thread(file.close)


async def _write_archive(
    session: AsyncSession,
    storage: Storage,
    project: Project,
    out: IO[bytes],
    *,
    shared_dir: Path,
    with_materials: bool,
) -> None:
    """Файлы проекта снимком из базы, затем общий класс и «Как собрать.txt», если в проекте
    нет файлов с такими путями: как при сборке, файл проекта главнее."""
    archive = zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED)
    try:
        paths: set[str] = set()
        blobs: list[ExportEntry] = []
        batches = service.iter_export_files(session, project.id, with_materials=with_materials)
        async with aclosing(batches):
            async for batch in batches:
                for entry in batch:
                    _check_member(project, entry.path)
                    paths.add(entry.path)
                blobs.extend(entry for entry in batch if entry.kind == "binary")
                inline = [entry for entry in batch if entry.kind != "binary"]
                await asyncio.to_thread(_write_inline, archive, inline)
        # Blob по sha256 не меняется — его можно дочитать и после конца снимка.
        await session.commit()
        for entry in blobs:
            await _write_blob(archive, storage, project, entry)
        extras = await asyncio.to_thread(_extra_files, project, shared_dir)
        extras = [(name, data) for name, data in extras if name not in paths]
        await asyncio.to_thread(_write_extras, archive, extras, datetime.now(MOSCOW))
    except BaseException:
        # Иначе оглавление допишет сборщик мусора (ZipFile.__del__) — уже в закрытый файл.
        with suppress(Exception):
            await asyncio.to_thread(archive.close)
        raise
    await asyncio.to_thread(archive.close)


def _check_member(project: Project, path: str) -> None:
    """Путь в архиве — путь проекта. Его проверили при записи (9.8), здесь — ещё раз то, от
    чего зависит, куда распакуется файл: без ведущего /, «.», «..», \\, «:» (диск Windows)
    и управляющих символов. Испорченная строка в базе не даст файл вне папки распаковки."""
    parts = path.split("/")
    safe = (
        "\\" not in path
        and ":" not in path
        and all(part not in ("", ".", "..") for part in parts)
        and not any(unicodedata.category(char) == "Cc" for char in path)
    )
    if not safe:
        logger.error("export_unsafe_path", project_id=str(project.id))
        raise AppError(ErrorCode.INTERNAL, INTERNAL_MESSAGE, 500)


def _write_inline(archive: zipfile.ZipFile, entries: list[ExportEntry]) -> None:
    """Папки и тексты пачки — в архив. Работа процессора: вызывается в потоке."""
    for entry in entries:
        if entry.kind == "folder":
            archive.mkdir(_info(entry.path, entry.updated_at, folder=True))
        else:
            archive.writestr(_info(entry.path, entry.updated_at), (entry.content or "").encode())


async def _write_blob(
    archive: zipfile.ZipFile, storage: Storage, project: Project, entry: ExportEntry
) -> None:
    """Картинка или документ из Storage — кусками, целиком в память не читается."""
    assert entry.blob_sha256 is not None
    try:
        stream = await storage.open_stream(entry.blob_sha256)
    except BlobNotFoundError:
        logger.error("export_blob_missing", project_id=str(project.id), sha256=entry.blob_sha256)
        raise AppError(
            ErrorCode.NOT_FOUND,
            f"Файл {entry.path} не найден в хранилище, архив не собран. Загрузите его заново.",
            404,
        ) from None
    info = _info(entry.path, entry.updated_at)
    # Размер заранее — чтобы zipfile сразу решил, нужен ли zip64.
    info.file_size = entry.size
    writer = await asyncio.to_thread(archive.open, info, "w")
    try:
        async for chunk in stream:
            await asyncio.to_thread(writer.write, chunk)
    finally:
        await asyncio.to_thread(writer.close)


def _extra_files(project: Project, shared_dir: Path) -> list[tuple[str, bytes]]:
    """Файлы общего класса (верхний уровень shared_dir, без скрытых) и «Как собрать.txt».

    Без класса архив вне BlaBlaTex не соберётся: \\documentclass{mtuci-report} его не найдёт.
    Нет папки — это ошибка установки: архив всё равно отдаётся, а в логе — ошибка.
    """
    files: list[tuple[str, bytes]] = []
    if shared_dir.is_dir():
        for path in sorted(shared_dir.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                files.append((path.name, path.read_bytes()))
    else:
        logger.error("export_shared_dir_missing", project_id=str(project.id))
    howto = _HOWTO_TEMPLATE.read_text(encoding="utf-8").replace("{main}", project.main_file)
    files.append((HOWTO_NAME, howto.encode()))
    return files


def _write_extras(archive: zipfile.ZipFile, files: list[tuple[str, bytes]], when: datetime) -> None:
    for name, data in files:
        archive.writestr(_info(name, when), data)


def _info(path: str, updated_at: datetime, *, folder: bool = False) -> zipfile.ZipInfo:
    """Запись архива: путь, местное время, права. Имя не из ASCII zipfile сам пишет в UTF-8
    с флагом UTF-8 (бит 11) — так его читают проводник Windows, macOS и 7-Zip."""
    date_time = max(updated_at.astimezone(MOSCOW).timetuple()[:6], _ZIP_EPOCH)
    info = zipfile.ZipInfo(f"{path}/" if folder else path, date_time=date_time)
    info.create_system = _UNIX
    if folder:
        # ZipFile.mkdir ждёт у записи папки готовые размеры и CRC.
        info.external_attr = _FOLDER_ATTR
        info.compress_type = zipfile.ZIP_STORED
        info.file_size = info.compress_size = info.CRC = 0
    else:
        info.external_attr = _FILE_ATTR
        stored = path.lower().endswith(STORED_EXTENSIONS)
        info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    return info
