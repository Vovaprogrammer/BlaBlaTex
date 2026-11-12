"""Проекты и их файлы. Другие модули работают с таблицами projects, files и историей
правок только здесь.

Каждый путь файла проходит validate_path (architecture.md 9.8), кто бы ни вызвал функцию.
Каждое изменение файлов попадает в changeset и сохраняет прежний вид файлов (history.py),
а после commit — в журнал событий проекта (9.3): так его видят другие вкладки. Кто пишет
и в какой changeset, говорит Writer: сайт, ИИ (ProjectTools), meta.tex или шаблон.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Collection, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import BinaryIO, Literal

import structlog
from sqlalchemy import (
    Select,
    String,
    Uuid,
    and_,
    case,
    cast,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
    tuple_,
    union,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql import ColumnElement

from app.core import blob_locks
from app.core.errors import AppError, ErrorCode, FieldError, request_error
from app.core.events import Author
from app.core.storage import BlobNotFoundError, Storage
from app.modules.materials import service as materials_service
from app.modules.projects import filetypes
from app.modules.projects.history import (
    SILENT,
    ProjectChange,
    RevertPlan,
    Segment,
    Writer,
    ensure_unlocked,
    lock_project,
    plan_revert,
)
from app.modules.projects.history import segments as changeset_segments
from app.modules.projects.models import Changeset, File, FileRevision, Project
from app.modules.projects.paths import (
    BINARY_FILE_TYPES,
    MATERIALS_DIR,
    MAX_PATH_LENGTH,
    TEXT_FILE_EXTENSIONS,
    InvalidPathError,
    is_material_path,
    is_text_file_type,
    validate_path,
)
from app.modules.projects.schemas import (
    Engine,
    FileKind,
    FileRole,
    ProjectKind,
    ProjectUpdate,
    RevertConflictReason,
)

logger = structlog.get_logger(__name__)

MB = 1024 * 1024
# Лимиты из 9.8 — в байтах (у текста — в UTF-8).
TEXT_FILE_MAX_BYTES = 2 * MB
PROJECT_MAX_BYTES = 200 * MB
UPLOAD_FILE_MAX_BYTES = 20 * MB
UPLOAD_MAX_FILES = 100
# Весь запрос загрузки: больше проекта всё равно не загрузить. Сверху — запас на заголовки
# частей multipart.
UPLOAD_REQUEST_MAX_BYTES = PROJECT_MAX_BYTES + MB
TEXT_MIME = "text/plain"
# Правила регистра Unicode без привязки к языку: есть в любом Postgres со сборкой ICU.
ICU_COLLATION = "und-x-icu"
PROJECT_NOT_FOUND_MESSAGE = "Проект не найден"
FILE_NOT_FOUND_MESSAGE = "Файл не найден"
PATH_NOT_FOUND_MESSAGE = "Файл или папка не найдены"
PATH_TAKEN_MESSAGE = "Файл или папка с таким путём уже есть"
GENERATED_FILE_MESSAGE = "Файл создаётся автоматически"
# Документы из materials/ (методичку, задание) читает только ИИ — в сборку они не идут.
# Регистр расширения не важен.
MATERIAL_DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".pptx", ".xlsx")
# Строк экспорта за одно чтение из курсора: тексты — до 2 МБ, в памяти не больше 32 МБ.
EXPORT_BATCH_ROWS = 16
_EXPORT_CURSOR = "bbt_export_files"


@dataclass(frozen=True)
class ExportEntry:
    """Файл или папка проекта для архива: у текста — содержимое, у бинарного — sha256."""

    path: str
    kind: FileKind
    content: str | None
    blob_sha256: str | None
    size: int
    updated_at: datetime


@dataclass(frozen=True)
class NewProject:
    """Новый проект: значения из манифеста шаблона и уже проверенные поля."""

    title: str
    template_slug: str
    template_version: int
    kind: ProjectKind
    engine: Engine
    main_file: str
    fields: dict[str, str | int]


async def create_project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    new: NewProject,
    files: Mapping[str, str],
    generated: Mapping[str, str] | None = None,
) -> Project:
    """Создаёт проект вместе с текстовыми файлами (путь → текст) одной транзакцией.

    files — файлы пользователя (role=source, в materials/ — material), generated — файлы,
    которые создаёт бэкенд (role=generated, это meta.tex). Проект без своих файлов
    не появится.
    Файлы проходят те же проверки, что запись пользователем: путь по 9.8, текстовый тип,
    до 2 МБ, без нулевого символа, весь проект — до 200 МБ. Папки над файлами создаются сами.
    Всё созданное — один changeset author=template от имени владельца (раздел 5); событий
    нет — проект ещё никто не смотрит.
    """
    groups: list[tuple[FileRole, Mapping[str, str]]] = [
        ("source", files),
        ("generated", generated or {}),
    ]
    # Путь → (текст, размер в байтах, роль).
    checked: dict[str, tuple[str, int, FileRole]] = {}
    for role, group in groups:
        for path, content in group.items():
            path = validate_path(path)
            _check_text_file_type(path)
            # Файл пользователя в materials/ — материал (9.8).
            file_role = role_for(path) if role == "source" else role
            checked[path] = (content, _check_text(content), file_role)
    if sum(size for _, size, _ in checked.values()) > PROJECT_MAX_BYTES:
        raise _project_too_large()
    project = Project(owner_id=owner_id, **asdict(new))
    session.add(project)
    # Строка проекта нужна в базе до папок: их вставка ссылается на project_id.
    await session.flush()
    # Блокировать новый проект незачем: до commit его не видит никто.
    change = ProjectChange(
        session,
        project.id,
        Writer(SILENT, "template", owner_id),
        last_version=project.last_file_version,
        last_changeset_id=None,
    )
    folders = sorted({folder for path in checked for folder in _parents(path)})
    await _ensure_folders(session, change, project.id, folders)
    created = [
        File(
            project_id=project.id,
            path=path,
            kind="text",
            role=role,
            content=content,
            mime=TEXT_MIME,
            size=size,
            version=change.next_version(),
        )
        for path, (content, size, role) in checked.items()
    ]
    session.add_all(created)
    # Строки material_text ссылаются на файлы: файлы — в базу раньше.
    await session.flush()
    await change.created([file.id for file in created])
    await materials_service.mark_pending(
        session, [file.id for file in created if file.role == "material"]
    )
    await change.save()
    await session.commit()
    return project


async def write_generated_file(
    session: AsyncSession, writer: Writer, project_id: uuid.UUID, path: str, content: str
) -> ProjectChange | None:
    """Пишет файл role=generated (meta.tex): создаёт его или заменяет текст.

    Коммит — за вызывающим: файл пересоздаётся вместе с полями проекта или профилем,
    в их транзакции. Проект блокируется, как при любой записи файлов, но не поднимается
    в списке — сам пользователь его не менял. Текст тот же — файл не трогается и версия
    не растёт. Проекта уже нет или по пути папка — файл не пишется: из-за одного
    такого проекта не должно падать сохранение профиля. Запись — новый changeset
    автора writer (author=system, раздел 5).

    Возвращает изменение, если файл создан или изменился, иначе None. После commit
    вызывающий рассылает его события: await change.publish().
    """
    path = validate_path(path)
    size = _check_text(content)
    change = await lock_project(session, project_id, writer, touch=False)
    if change is None:
        return None
    file = await session.scalar(
        select(File).where(File.project_id == project_id, File.path == path)
    )
    if file is None:
        await _ensure_folders(session, change, project_id, _parents(path))
        file = File(
            project_id=project_id,
            path=path,
            kind="text",
            role="generated",
            content=content,
            mime=TEXT_MIME,
            size=size,
            version=change.next_version(),
        )
        session.add(file)
        await session.flush()
        await change.created([file.id])
    elif file.kind != "text":
        logger.warning("generated_file_skipped", project_id=str(project_id), path=path)
        return None
    elif file.content == content and file.role == "generated":
        return None
    else:
        await change.snapshot(File.id == file.id)
        # Файл с таким именем мог создать сам пользователь — теперь он генерируется.
        file.content = content
        file.size = size
        file.role = "generated"
        file.version = change.next_version()
    change.file_changed(file.path, file.version)
    await change.save()
    return change


async def list_projects(session: AsyncSession, owner_id: uuid.UUID) -> list[Project]:
    """Проекты владельца, недавно изменённые — первыми."""
    result = await session.scalars(
        select(Project)
        .where(Project.owner_id == owner_id)
        .order_by(Project.updated_at.desc(), Project.created_at.desc())
    )
    return list(result)


async def get_owned_project(
    session: AsyncSession, project_id: uuid.UUID, owner_id: uuid.UUID
) -> Project | None:
    """Проект владельца или None: чужой и несуществующий проект не различаются."""
    return await session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    """Проект по id без проверки владельца — для фоновых задач, которые взяли id из своей
    записи (например, сборки). В обработчиках запросов — только get_owned_project."""
    return await session.get(Project, project_id)


async def update_project(session: AsyncSession, project: Project, data: ProjectUpdate) -> Project:
    """Меняет только переданные поля; null — то же, что поле не передано.

    fields заменяются целиком; по манифесту шаблона их проверяет модуль шаблонов.
    """
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(project, field, value)
    await session.commit()
    return project


async def delete_project(session: AsyncSession, project: Project) -> None:
    """Удаляет проект; его файлы база удаляет сама (ON DELETE CASCADE).

    Пока проект держит прогон агента — 423: сначала его нужно остановить.
    """
    await ensure_unlocked(session, project.id)
    await session.delete(project)
    await session.commit()


async def owner_blobs(session: AsyncSession, owner_id: uuid.UUID) -> set[str]:
    """sha256 бинарных файлов и ревизий во всех проектах владельца."""
    files = (
        select(File.blob_sha256)
        .join(Project, Project.id == File.project_id)
        .where(Project.owner_id == owner_id, File.blob_sha256.is_not(None))
    )
    revisions = (
        select(FileRevision.blob_sha256)
        .join(Changeset, Changeset.id == FileRevision.changeset_id)
        .join(Project, Project.id == Changeset.project_id)
        .where(Project.owner_id == owner_id, FileRevision.blob_sha256.is_not(None))
    )
    return {sha256 for sha256 in await session.scalars(union(files, revisions)) if sha256}


async def referenced_blobs(session: AsyncSession, sha256s: Collection[str]) -> set[str]:
    """Какие из sha256 упомянуты в файлах или ревизиях любого проекта."""
    if not sha256s:
        return set()
    wanted = list(sha256s)
    files = select(File.blob_sha256).where(File.blob_sha256.in_(wanted))
    revisions = select(FileRevision.blob_sha256).where(FileRevision.blob_sha256.in_(wanted))
    return {sha256 for sha256 in await session.scalars(union(files, revisions)) if sha256}


def file_too_large() -> AppError:
    return AppError(ErrorCode.PAYLOAD_TOO_LARGE, "Текстовый файл не может быть больше 2 МБ", 413)


def _check_text_file_type(path: str) -> None:
    if not is_text_file_type(path):
        raise AppError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            f"Файл {path} не сохранить текстом. Подходят: {' '.join(TEXT_FILE_EXTENSIONS)}",
            415,
        )


def _project_too_large() -> AppError:
    return AppError(
        ErrorCode.PAYLOAD_TOO_LARGE,
        f"Проект не может быть больше {PROJECT_MAX_BYTES // (1024 * 1024)} МБ. "
        "Удалите ненужные файлы.",
        413,
    )


def _check_text(content: str) -> int:
    """Проверяет текст файла и возвращает его размер в байтах UTF-8."""
    size = len(content.encode())
    if size > TEXT_FILE_MAX_BYTES:
        raise file_too_large()
    # Postgres не хранит нулевой символ в тексте.
    if "\x00" in content:
        raise _invalid("В тексте не может быть нулевого символа")
    return size


def role_for(path: str) -> FileRole:
    """Роль файла пользователя по пути (9.8): в materials/ — material, иначе source."""
    return "material" if is_material_path(path) else "source"


def _check_binary_rename(from_path: str, to_path: str) -> None:
    """Тип бинарного файла определён по содержимому при загрузке, поэтому расширение
    меняется только на расширение того же типа: .jpg на .jpeg можно, .png на .pdf — нет."""
    old = BINARY_FILE_TYPES.get(PurePosixPath(from_path).suffix.lower())
    new = BINARY_FILE_TYPES.get(PurePosixPath(to_path).suffix.lower())
    if new is None or new != old:
        raise AppError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            f"Файл {from_path} не переименовать в {PurePosixPath(to_path).name}: "
            "расширение должно соответствовать содержимому файла",
            415,
        )


async def _project_size(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Сколько байт уже занимают файлы проекта (9.8)."""
    used = await session.scalar(
        select(func.coalesce(func.sum(File.size), 0)).where(File.project_id == project_id)
    )
    return used or 0


def _not_found(message: str = FILE_NOT_FOUND_MESSAGE) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, message, 404)


def _path_taken() -> AppError:
    return AppError(ErrorCode.ALREADY_EXISTS, PATH_TAKEN_MESSAGE, 409)


def _generated_file() -> AppError:
    return AppError(ErrorCode.FORBIDDEN, GENERATED_FILE_MESSAGE, 403)


def _reject_ai_in_materials(writer: Writer, *paths: str) -> None:
    """403, если ИИ меняет материал или саму папку materials (9.4): материалы приносит
    студент, и ИИ не должен выдать придуманный вывод программы за них."""
    if writer.author != "ai":
        return
    for path in paths:
        if path == MATERIALS_DIR or is_material_path(path):
            raise AppError(
                ErrorCode.FORBIDDEN, "Материалы меняет только студент, ИИ их только читает", 403
            )


def _invalid(message: str) -> AppError:
    # Ошибка не привязана к одному полю, поэтому список ошибок по полям пуст.
    return AppError(ErrorCode.VALIDATION_ERROR, message, 422, {"errors": []})


def _parents(path: str) -> list[str]:
    """Папки над путём, от верхней: a/b/c.tex → [a, a/b]."""
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _in_folder(folder: str) -> ColumnElement[bool]:
    """Условие «путь внутри папки». Экранирование нужно: _ и % в именах — спецсимволы LIKE."""
    return File.path.startswith(folder + "/", autoescape=True)


def _select_file(project_id: uuid.UUID, path: str) -> Select[tuple[File]]:
    """Файл или папка по пути, без содержимого: оно бывает до 2 МБ и здесь не нужно."""
    return (
        select(File)
        .where(File.project_id == project_id, File.path == path)
        .options(defer(File.content, raiseload=True))
    )


async def _find(session: AsyncSession, project_id: uuid.UUID, path: str) -> File | None:
    return await session.scalar(_select_file(project_id, path))


async def _reject_generated(session: AsyncSession, target: File) -> None:
    """403, если target — файл role=generated или папка, в которой такой файл лежит (9.6).

    Такие файлы меняет только бэкенд (write_generated_file), а правка через API молча
    пропала бы при следующем пересоздании. Вложенные файлы папки ищутся по префиксу пути
    одним запросом, без обхода дерева.
    """
    if target.role == "generated":
        raise _generated_file()
    if target.kind != "folder":
        return
    generated = await session.scalar(
        select(File.path)
        .where(
            File.project_id == target.project_id,
            File.role == "generated",
            _in_folder(target.path),
        )
        .limit(1)
    )
    if generated is not None:
        raise AppError(
            ErrorCode.FORBIDDEN, f"В папке есть файл {generated}, он создаётся автоматически", 403
        )


@asynccontextmanager
async def _changing_files(
    session: AsyncSession, writer: Writer, project_id: uuid.UUID
) -> AsyncIterator[ProjectChange]:
    """Изменение файлов проекта: блокирует проект (lock_project), а при любой ошибке
    откатывает транзакцию. Проект успели удалить — 404.

    Без отката блокировка и соединение жили бы до закрытия сессии. В HTTP это сразу после
    ответа, а агент (этап 2) после ошибки инструмента продолжает с той же сессией — и все
    правки проекта ждали бы его. После отката загруженные объекты сессии сброшены:
    подгрузить их заново в async нельзя, поэтому после ошибки работают только с id.
    """
    try:
        change = await lock_project(session, project_id, writer)
        if change is None:
            raise AppError(ErrorCode.NOT_FOUND, PROJECT_NOT_FOUND_MESSAGE, 404)
        yield change
    except Exception:
        await session.rollback()
        raise


async def _ensure_folders(
    session: AsyncSession, change: ProjectChange, project_id: uuid.UUID, paths: list[str]
) -> None:
    """Создаёт недостающие папки и отмечает их в changeset. Если на месте одной из них
    уже файл — 409.

    Изменения не коммитит и вызывается внутри _changing_files: при ошибке тот откатит
    и уже вставленные папки.
    """
    if not paths:
        return
    rows = [
        {"project_id": project_id, "path": path, "kind": "folder", "role": "source"}
        for path in paths
    ]
    # Уже существующие папки пропускаются: в ответе только вставленные.
    inserted = await session.scalars(
        insert(File)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["project_id", "path"])
        .returning(File.id)
    )
    await change.created(list(inserted))
    clash = await session.scalar(
        select(File.path)
        .where(File.project_id == project_id, File.path.in_(paths), File.kind != "folder")
        .limit(1)
    )
    if clash is not None:
        raise AppError(ErrorCode.ALREADY_EXISTS, f"На месте папки {clash} уже есть файл", 409)


async def list_files(session: AsyncSession, project_id: uuid.UUID) -> list[File]:
    """Все файлы и папки проекта по пути. Содержимое не загружается: его могут быть мегабайты."""
    result = await session.scalars(
        select(File)
        .where(File.project_id == project_id)
        .order_by(File.path)
        .options(defer(File.content, raiseload=True))
    )
    return list(result)


async def list_build_files(session: AsyncSession, project_id: uuid.UUID) -> list[File]:
    """Файлы, которые уходят в сборку (architecture.md 6), вместе с содержимым текстовых.

    Это весь проект (role source и generated) и материалы, кроме документов: код
    и скриншоты из материалов отчёт подключает через \\bbtCodeFile и \\bbtScreenshot.
    Папки не нужны: в архиве они следуют из путей файлов.
    """
    result = await session.scalars(
        select(File)
        .where(File.project_id == project_id, File.kind != "folder", _goes_to_build())
        .order_by(File.path)
    )
    return list(result)


async def iter_export_files(
    session: AsyncSession, project_id: uuid.UUID, *, with_materials: bool
) -> AsyncIterator[list[ExportEntry]]:
    """Файлы и папки проекта для архива (architecture.md 9.1, «Экспорт»), по пути, пачками.

    Без with_materials — то, что уходит в сборку, и все папки; с ним — весь проект.

    Всё читается одним запросом — курсором Postgres (DECLARE), а он видит снимок базы
    на момент объявления: правка, закоммиченная посреди чтения (например, ИИ), в архив
    не попадёт даже наполовину. Строки приходят по EXPORT_BATCH_ROWS (FETCH): тексты
    проекта до 200 МБ не читаются в память разом. session.stream() так не умеет — драйвер
    сам подчитывает из курсора по 50 строк. Курсор живёт в транзакции сессии — её
    завершает вызывающий, когда прочитает всё. Прочитанный до конца курсор закрывается
    сразу, брошенный на полпути — вместе с транзакцией.
    """
    condition = File.project_id == project_id
    if not with_materials:
        condition = and_(condition, _goes_to_build())
    query = (
        select(File.path, File.kind, File.content, File.blob_sha256, File.size, File.updated_at)
        .where(condition)
        .order_by(File.path)
    )
    # Значения в запросе — uuid проекта и константы модуля, их можно вписать текстом.
    # exec_driver_sql — SQL уходит как есть: text() искал бы в нём параметры «:имя».
    connection = await session.connection()
    sql = query.compile(dialect=connection.dialect, compile_kwargs={"literal_binds": True})
    await connection.exec_driver_sql(f"DECLARE {_EXPORT_CURSOR} NO SCROLL CURSOR FOR {sql}")
    fetch = f"FETCH {EXPORT_BATCH_ROWS} FROM {_EXPORT_CURSOR}"
    while rows := (await connection.exec_driver_sql(fetch)).all():
        yield [ExportEntry(*row) for row in rows]
    await connection.exec_driver_sql(f"CLOSE {_EXPORT_CURSOR}")


def _goes_to_build() -> ColumnElement[bool]:
    """Файл уходит в сборку (architecture.md 6): весь проект и материалы, кроме документов.
    Папки — role source, так что условие верно и для них."""
    is_document = or_(
        *(func.lower(File.path).endswith(ext) for ext in MATERIAL_DOCUMENT_EXTENSIONS)
    )
    return or_(
        File.role.in_(("source", "generated")),
        and_(File.role == "material", ~is_document),
    )


async def read_file(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Файл вместе с содержимым: у текстового — текст, у бинарного — sha256 его blob'а
    в Storage (открывает open_binary). Нет файла или это папка — 404."""
    file = await session.scalar(
        select(File).where(File.project_id == project_id, File.path == validate_path(path))
    )
    if file is None or file.kind == "folder":
        raise _not_found()
    return file


async def get_file(session: AsyncSession, file_id: uuid.UUID) -> File | None:
    """Файл по id вместе с содержимым, как read_file, или None. Для задач воркера, которые
    знают только id файла (извлечение текста материалов)."""
    return await session.scalar(
        select(File).where(File.id == file_id).execution_options(populate_existing=True)
    )


async def get_path(session: AsyncSession, file_id: uuid.UUID) -> str | None:
    """Путь файла сейчас — файл могли перенести, пока задача воркера с ним работала."""
    return await session.scalar(select(File.path).where(File.id == file_id))


async def read_text_file(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Текстовый файл вместе с содержимым. Нет файла, это папка или бинарный файл — 404."""
    file = await read_file(session, project_id, path)
    if file.kind != "text":
        raise _not_found()
    return file


async def find_file(session: AsyncSession, project_id: uuid.UUID, path: str) -> File | None:
    """Файл или папка по пути, без содержимого, или None."""
    return await _find(session, project_id, validate_path(path))


async def list_material_files(session: AsyncSession, project_id: uuid.UUID) -> list[File]:
    """Файлы из materials/ по пути, без содержимого — для list_materials у агента."""
    result = await session.scalars(
        select(File)
        .where(File.project_id == project_id, File.role == "material", File.kind != "folder")
        .order_by(File.path)
        .options(defer(File.content, raiseload=True))
    )
    return list(result)


async def search_text_files(
    session: AsyncSession, project_id: uuid.UUID, query: str
) -> list[tuple[str, str]]:
    """Текстовые файлы проекта, где есть query без учёта регистра: пары (путь, текст).

    Отбирает база (ILIKE), а строки находит search_texts из tools.py — у фейка и настоящей
    ProjectTools одинаково. % и _ в query — обычные символы. Регистр сравнивается по ICU,
    как в Python, а не по локали базы: «ЦЕЛЬ» найдёт «Цель» на любой установке Postgres.
    """
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = await session.execute(
        select(File.path, File.content).where(
            File.project_id == project_id,
            File.kind == "text",
            File.content.collate(ICU_COLLATION).ilike(f"%{escaped}%", escape="\\"),
        )
    )
    return [(row.path, row.content) for row in rows]


async def open_binary(storage: Storage, file: File) -> AsyncIterator[bytes]:
    """Содержимое бинарного файла потоком из Storage: файл до 20 МБ не читается в память.

    Blob'а нет — 404 и запись в лог: в базе файл есть, а содержимое потеряно
    (например, хранилище в dev очистили). Помогает только загрузить файл заново.
    """
    if file.blob_sha256 is None:
        raise _not_found()
    try:
        return await storage.open_stream(file.blob_sha256)
    except BlobNotFoundError:
        logger.error(
            "file_blob_missing",
            project_id=str(file.project_id),
            file_id=str(file.id),
            sha256=file.blob_sha256,
        )
        raise AppError(
            ErrorCode.NOT_FOUND, "Содержимое файла потеряно. Загрузите его ещё раз.", 404
        ) from None


async def write_text_file(
    session: AsyncSession,
    writer: Writer,
    project_id: uuid.UUID,
    path: str,
    content: str,
    *,
    expected_version: int | None = None,
    create_only: bool = False,
) -> tuple[File, bool]:
    """Записывает текстовый файл; второе значение — True, если файл создан.

    expected_version — версия, которую правил пользователь: файл с тех пор изменили
    или удалили — 412 file_conflict с current_version. create_only — только создать:
    файл уже есть — 409. Промежуточные папки создаются сами. Тип файла не из 9.8 — 415,
    проект станет больше 200 МБ — 413. Файл role=generated — 403 (9.6), материал от ИИ — 403.
    """
    path = validate_path(path)
    _reject_ai_in_materials(writer, path)
    size = _check_text(content)
    async with _changing_files(session, writer, project_id) as change:
        file = await _find(session, project_id, path)
        # Бинарный файл (картинку, документ) дальше отсечёт проверка типа — 415.
        if file is not None and file.kind == "folder":
            raise AppError(ErrorCode.ALREADY_EXISTS, "По этому пути уже есть папка", 409)
        # Раньше версии: запись не пройдёт при любой версии, а 412 позвал бы перечитать
        # файл и повторить. Так и по RFC 9110 (13.2.1) — условия запроса проверяются,
        # только если без них ответ был бы 2xx или 412.
        if file is not None and file.role == "generated":
            raise _generated_file()
        # После проверки на папку: у папок нет типа, и «тут папка» — понятнее.
        _check_text_file_type(path)
        if expected_version is not None and (file is None or file.version != expected_version):
            raise AppError(
                ErrorCode.FILE_CONFLICT,
                "Файл изменён в другом месте" if file else "Файл удалён в другом месте",
                412,
                {"current_version": file.version if file else None},
            )
        if create_only and file is not None:
            raise _path_taken()
        used = await _project_size(session, project_id)
        if used - (file.size if file else 0) + size > PROJECT_MAX_BYTES:
            raise _project_too_large()

        created = file is None
        if file is None:
            await _ensure_folders(session, change, project_id, _parents(path))
            file = File(
                project_id=project_id,
                path=path,
                kind="text",
                role=role_for(path),
                content=content,
                mime=TEXT_MIME,
                size=size,
                version=change.next_version(),
            )
            session.add(file)
            await session.flush()
            await change.created([file.id])
        else:
            await change.snapshot(File.id == file.id)
            file.content = content
            file.size = size
            file.version = change.next_version()
        if file.role == "material":
            # Новый материал или новый текст материала: извлечь заново (раздел 5).
            await session.flush()
            change.materials_pending(await materials_service.mark_pending(session, [file.id]))
        change.file_changed(file.path, file.version)
        await change.save()
        await session.commit()
    await change.publish()
    return file, created


async def edit_text_file(
    session: AsyncSession,
    writer: Writer,
    project_id: uuid.UUID,
    path: str,
    edit: Callable[[str], str],
) -> File:
    """Меняет текст файла функцией edit: старый текст → новый (edit_file у агента).

    Чтение и запись — под одной блокировкой проекта: между ними файл никто не изменит.
    Нет файла или это папка — 404, файл не текстовый — 415, role=generated или материал
    от ИИ — 403; новый текст — те же проверки, что у write_text_file (2 МБ, нулевой символ,
    200 МБ на проект). Исключение из edit откатывает изменение и выходит наружу.
    """
    path = validate_path(path)
    _reject_ai_in_materials(writer, path)
    async with _changing_files(session, writer, project_id) as change:
        file = await session.scalar(
            select(File).where(File.project_id == project_id, File.path == path)
        )
        if file is None or file.kind == "folder":
            raise _not_found()
        if file.content is None:
            raise AppError(
                ErrorCode.UNSUPPORTED_FILE_TYPE,
                f"Файл {path} не текстовый, текстом его не изменить",
                415,
            )
        if file.role == "generated":
            raise _generated_file()
        content = edit(file.content)
        size = _check_text(content)
        if await _project_size(session, project_id) - file.size + size > PROJECT_MAX_BYTES:
            raise _project_too_large()
        await change.snapshot(File.id == file.id)
        file.content = content
        file.size = size
        file.version = change.next_version()
        if file.role == "material":
            change.materials_pending(await materials_service.mark_pending(session, [file.id]))
        change.file_changed(file.path, file.version)
        await change.save()
        await session.commit()
    await change.publish()
    return file


@dataclass(frozen=True)
class IncomingFile:
    """Файл из запроса загрузки: имя, как его прислал клиент, и содержимое во временном файле."""

    name: str
    file: BinaryIO
    size: int


@dataclass(frozen=True)
class CheckedUpload:
    """Файл загрузки после проверок без базы: путь по 9.8, вид, MIME и размер в проекте."""

    path: str
    kind: Literal["text", "binary"]
    mime: str
    # У текста — байты UTF-8 после перекодировки: столько он займёт в проекте.
    size: int
    source: BinaryIO


async def check_uploads(folder: str, incoming: Sequence[IncomingFile]) -> list[CheckedUpload]:
    """Проверки загрузки, которым не нужна база (9.1), — по этапам для всех файлов сразу.

    Сначала то, что видно по имени: путь (422) и тип по расширению (415), затем размер (413)
    и только потом содержимое (415): большой файл с неподходящим именем не читается.
    Первая ошибка называет файл — в message и в details.path. Файлы никуда не пишутся.
    """
    if not incoming:
        raise _invalid("Выберите файлы для загрузки")
    if len(incoming) > UPLOAD_MAX_FILES:
        raise _invalid(f"За один раз можно загрузить не больше {UPLOAD_MAX_FILES} файлов")
    prefix = _upload_prefix(folder)
    paths = [_upload_path(prefix, item.name, index) for index, item in enumerate(incoming)]
    # Путь, который нужен как папка для другого файла запроса, файлом быть не может.
    folders = {parent for path in paths for parent in _parents(path)}
    seen: set[str] = set()
    for index, path in enumerate(paths):
        if path in seen:
            raise _bad_upload_name(index, path, "файл выбран дважды")
        if path in folders:
            raise _bad_upload_name(index, path, "это и файл, и папка для других файлов")
        seen.add(path)
    for path in paths:
        _check_upload_type(path)
    for path, item in zip(paths, incoming, strict=True):
        _check_upload_size(path, item.size)
    # Содержимое читается с диска — в отдельном потоке, по одному файлу.
    return [
        await asyncio.to_thread(_check_upload_content, path, item)
        for path, item in zip(paths, incoming, strict=True)
    ]


async def save_uploads(
    session: AsyncSession,
    storage: Storage,
    writer: Writer,
    project_id: uuid.UUID,
    uploads: Sequence[CheckedUpload],
) -> list[File]:
    """Сохраняет проверенные файлы загрузки одной транзакцией: всё или ничего (9.1).

    Под блокировкой проекта проверяются занятые пути: файл role=generated — 403, папка
    на месте файла или файл на месте папки над ним — 409; затем размер проекта — 413.
    Файл по этому пути уже есть — заменяется, версия растёт. Роль задаёт путь:
    в materials/ — material, иначе source.

    Бинарные файлы попадают в Storage только после этих проверок, чтобы из-за отказа
    в хранилище не оставались ненужные файлы. Текст пишется в базу по одному файлу
    и сразу выгружается из памяти: сто текстовых файлов не лежат в ней все вместе.
    """
    paths = [upload.path for upload in uploads]
    async with _changing_files(session, writer, project_id) as change:
        existing = {
            file.path: file
            for file in await session.scalars(
                select(File)
                .where(File.project_id == project_id, File.path.in_(paths))
                .options(defer(File.content, raiseload=True))
            )
        }
        for path in paths:
            file = existing.get(path)
            if file is not None and file.kind == "folder":
                raise AppError(
                    ErrorCode.ALREADY_EXISTS, f"По пути {path} уже есть папка", 409, {"path": path}
                )
            if file is not None and file.role == "generated":
                raise AppError(
                    ErrorCode.FORBIDDEN,
                    f"Файл {path} создаётся автоматически, его не заменить",
                    403,
                    {"path": path},
                )
        # Папка → первый файл загрузки, которому она нужна: его путь и уйдёт в details.path.
        folders = {parent: path for path in reversed(paths) for parent in _parents(path)}
        clash = await session.scalar(
            select(File.path)
            .where(
                File.project_id == project_id, File.path.in_(list(folders)), File.kind != "folder"
            )
            .order_by(File.path)
            .limit(1)
        )
        if clash is not None:
            raise AppError(
                ErrorCode.ALREADY_EXISTS,
                f"На месте папки {clash} уже есть файл",
                409,
                {"path": folders[clash]},
            )
        await _ensure_folders(session, change, project_id, sorted(folders))
        replaced = sum(file.size for file in existing.values())
        added = sum(upload.size for upload in uploads)
        if await _project_size(session, project_id) - replaced + added > PROJECT_MAX_BYTES:
            raise _project_too_large()

        if existing:
            await change.snapshot(File.id.in_([file.id for file in existing.values()]))
        saved = [
            await _save_upload(session, storage, change, upload, existing.get(upload.path))
            for upload in uploads
        ]
        # И новый материал, и загруженный заново — снова в очередь на извлечение текста.
        pending = await materials_service.mark_pending(
            session, [file.id for file in saved if file.role == "material"]
        )
        change.materials_pending(pending)
        for file in saved:
            change.file_changed(file.path, file.version)
        await change.save()
        await session.commit()
    await change.publish()
    return saved


def upload_error(loc: list[str | int], message: str) -> AppError:
    """422 формы загрузки: текст — и в message, его покажет интерфейс, и у поля в loc."""
    error = FieldError(loc=loc, type="value_error", message=message)
    return AppError(ErrorCode.VALIDATION_ERROR, message, 422, {"errors": [error.model_dump()]})


def _upload_prefix(folder: str) -> str:
    """Папка загрузки как начало пути: пусто — корень проекта."""
    if not folder:
        return ""
    try:
        return validate_path(folder) + "/"
    except InvalidPathError as error:
        raise upload_error(["body", "dir"], f"Папка «{folder}»: {error}") from None


def _upload_path(prefix: str, name: str, index: int) -> str:
    if not name:
        raise _bad_upload_name(index, prefix, "у файла нет имени")
    try:
        return validate_path(prefix + name)
    except InvalidPathError as error:
        raise _bad_upload_name(index, prefix + name, str(error)) from None


def _bad_upload_name(index: int, path: str, reason: str) -> AppError:
    """422 с файлом в тексте ошибки: имя ошибки поля (loc) — номер файла в запросе."""
    reason = reason[0].lower() + reason[1:]
    error = FieldError(loc=["body", "files", index], type="invalid_path", message=reason)
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        f"Файл «{path}»: {reason}",
        422,
        {"errors": [error.model_dump()], "path": path},
    )


def _check_upload_type(path: str) -> None:
    if is_text_file_type(path) or PurePosixPath(path).suffix.lower() in BINARY_FILE_TYPES:
        return
    allowed = " ".join((*TEXT_FILE_EXTENSIONS, *BINARY_FILE_TYPES))
    raise filetypes.unsupported(
        path, f"Файл {path} не загрузить: такой тип не поддерживается. Подходят: {allowed}"
    )


def _check_upload_size(path: str, size: int) -> None:
    """Файл до 20 МБ, текстовый — до 2 МБ (9.8). У текста лимит проверяется ещё раз
    после перекодировки: в UTF-8 русский текст из cp1251 занимает вдвое больше."""
    text = is_text_file_type(path)
    limit = TEXT_FILE_MAX_BYTES if text else UPLOAD_FILE_MAX_BYTES
    if size > limit:
        what = "Текстовый файл" if text else "Файл"
        raise AppError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"{what} {path} больше {limit // MB} МБ",
            413,
            {"path": path},
        )


def _check_upload_content(path: str, item: IncomingFile) -> CheckedUpload:
    """Содержимое соответствует типу (415). Текст проверяется и сразу забывается:
    в базу его перечитает save_uploads, по одному файлу."""
    if not is_text_file_type(path):
        mime = filetypes.check_binary(path, item.file)
        return CheckedUpload(path, "binary", mime, item.size, item.file)
    size = len(_read_upload_text(path, item.file).encode())
    _check_upload_size(path, size)
    return CheckedUpload(path, "text", TEXT_MIME, size, item.file)


def _read_upload_text(path: str, source: BinaryIO) -> str:
    source.seek(0)
    return filetypes.decode_text(path, source.read())


async def _save_upload(
    session: AsyncSession,
    storage: Storage,
    change: ProjectChange,
    upload: CheckedUpload,
    file: File | None,
) -> File:
    """Записывает один файл загрузки: новый или поверх старого. Коммит — за вызывающим.

    Прежний вид заменяемых файлов вызывающий уже сохранил (snapshot), новый файл
    отмечается здесь.
    """
    created = file is None
    if file is None:
        file = File(project_id=change.project_id, path=upload.path)
        session.add(file)
    file.version = change.next_version()
    file.kind, file.mime, file.size = upload.kind, upload.mime, upload.size
    file.role = role_for(upload.path)
    if upload.kind == "text":
        file.content = await asyncio.to_thread(_read_upload_text, upload.path, upload.source)
        file.blob_sha256 = None
    else:
        file.content = None
        # Замок на blob — до commit загрузки: уборка хранилища не удалит такой же файл
        # другого студента, пока ссылки на него ещё нет (architecture.md 5).
        file.blob_sha256 = await blob_locks.put_held(session, storage, upload.source)
    await session.flush()
    if created:
        await change.created([file.id])
    if upload.kind == "text":
        # Текст уже в базе: объект его больше не держит, память не копится от файла к файлу.
        session.expire(file, ["content"])
    return file


async def create_folder(
    session: AsyncSession, writer: Writer, project_id: uuid.UUID, path: str
) -> File:
    """Создаёт папку вместе с недостающими папками над ней. Путь уже занят — 409.

    Вкладкам уходит file.changed с путём новой папки: папки — тоже строки дерева файлов.
    """
    path = validate_path(path)
    async with _changing_files(session, writer, project_id) as change:
        if await _find(session, project_id, path) is not None:
            raise _path_taken()
        await _ensure_folders(session, change, project_id, [*_parents(path), path])
        folder = (await session.execute(_select_file(project_id, path))).scalar_one()
        change.file_changed(folder.path, folder.version)
        await change.save()
        await session.commit()
    await change.publish()
    return folder


async def move_path(
    session: AsyncSession,
    writer: Writer,
    project_id: uuid.UUID,
    from_path: str,
    to_path: str,
) -> File:
    """Переносит или переименовывает файл или папку вместе со всем содержимым.

    Пути вложенных файлов меняются одним UPDATE в той же транзакции. Версии не меняются:
    версия — про содержимое, и открытый в редакторе файл сохранится без ложного конфликта.
    Роль — по новому пути (9.8): перенесённое в materials/ становится материалом, из неё —
    обычным файлом. Папки над новым путём создаются сами. Файл role=generated и папку
    с ним — 403 (9.6). Вкладкам уходит одно событие file.moved, и для папки тоже: всё
    внутри неё переехало вместе с ней.
    """
    from_path, to_path = validate_path(from_path), validate_path(to_path)
    _reject_ai_in_materials(writer, from_path, to_path)
    if to_path == from_path:
        # Перемещать нечего, и блокировать проект незачем.
        source = await _find(session, project_id, from_path)
        if source is None:
            raise _not_found(PATH_NOT_FOUND_MESSAGE)
        return source
    async with _changing_files(session, writer, project_id) as change:
        source = await _find(session, project_id, from_path)
        if source is None:
            raise _not_found(PATH_NOT_FOUND_MESSAGE)
        await _reject_generated(session, source)
        is_folder = source.kind == "folder"
        # Файл «внутрь себя» отсекает _ensure_folders: на месте папки окажется файл — 409.
        if is_folder and to_path.startswith(from_path + "/"):
            raise _invalid("Нельзя переместить папку внутрь неё самой")
        if await _find(session, project_id, to_path) is not None:
            raise _path_taken()
        # Переименование не должно превращать текст в «картинку», а картинку — в PDF.
        if source.kind == "text":
            _check_text_file_type(to_path)
        elif source.kind == "binary":
            _check_binary_rename(from_path, to_path)
        if is_folder:
            longest = await session.scalar(
                select(func.max(func.char_length(File.path))).where(
                    File.project_id == project_id, _in_folder(from_path)
                )
            )
            if longest is not None and longest - len(from_path) + len(to_path) > MAX_PATH_LENGTH:
                raise _invalid(f"Путь вложенного файла станет длиннее {MAX_PATH_LENGTH} символов")

        # Прежние пути — в ревизии: у папки это все вложенные файлы и папки.
        moved = File.id == source.id
        await change.snapshot(or_(moved, _in_folder(from_path)) if is_folder else moved)
        await _ensure_folders(session, change, project_id, _parents(to_path))
        if is_folder:
            # Новый путь — новый префикс и остаток старого пути после «папка/». Роль у всех
            # вложенных файлов одна: она зависит только от того, в materials/ ли новый путь.
            # Папки остаются source, файлов role=generated внутри нет — их отсекла проверка.
            rest = func.substr(File.path, len(from_path) + 2)
            await session.execute(
                update(File)
                .where(File.project_id == project_id, _in_folder(from_path))
                .values(
                    path=func.concat(to_path + "/", rest),
                    role=case(
                        (File.kind == "folder", File.role), else_=literal(role_for(to_path + "/"))
                    ),
                )
            )
        else:
            source.role = role_for(to_path)
        source.path = to_path
        await _sync_moved_materials(session, change, project_id, source, to_path)
        change.file_moved(from_path, to_path)
        await change.save()
        await session.commit()
    await change.publish()
    return source


async def _sync_moved_materials(
    session: AsyncSession, change: ProjectChange, project_id: uuid.UUID, source: File, to_path: str
) -> None:
    """После переноса: материалам — строки material_text, ушедшим из materials/ — без них.

    Перенесённый внутри materials/ файл сохраняет уже извлечённый текст (раздел 5).
    """
    if source.kind == "folder":
        moved = list(
            await session.scalars(
                select(File.id).where(
                    File.project_id == project_id, _in_folder(to_path), File.kind != "folder"
                )
            )
        )
        is_material = is_material_path(to_path + "/")
    else:
        moved, is_material = [source.id], source.role == "material"
    if is_material:
        change.materials_pending(await materials_service.keep_or_add(session, moved))
    else:
        await materials_service.forget(session, moved)


async def delete_path(
    session: AsyncSession, writer: Writer, project_id: uuid.UUID, path: str
) -> None:
    """Удаляет файл или папку со всем содержимым. Нет такого пути — 404.

    Файл role=generated и папку с ним — 403 (9.6). Удалённое остаётся в ревизиях changeset:
    текст — копией, бинарный файл — ссылкой на blob в Storage (тот же blob бывает и у других
    файлов). Неиспользуемые blob'ы удаляет очистка хранилища (B3.3). Вкладкам уходит одно
    событие file.deleted, и для папки тоже. Материал от ИИ — 403.
    """
    path = validate_path(path)
    _reject_ai_in_materials(writer, path)
    async with _changing_files(session, writer, project_id) as change:
        target = await _find(session, project_id, path)
        if target is None:
            raise _not_found(PATH_NOT_FOUND_MESSAGE)
        await _reject_generated(session, target)
        removed = or_(File.path == path, _in_folder(path))
        await change.snapshot(removed)
        await session.execute(delete(File).where(File.project_id == project_id, removed))
        change.file_deleted(path)
        await change.save()
        await session.commit()
    await change.publish()


# История правок: список и откат (architecture.md 9.1). Что изменил changeset — history.py.

CHANGESET_NOT_FOUND_MESSAGE = "Правки не найдены"
# Эти changesets не откатываются.
NOT_REVERTED: dict[Author, str] = {
    "template": "Создание проекта не откатить",
    "system": "Обновление meta.tex не откатить: он собирается из профиля и полей проекта",
}
# Путь файла, пока откат переставляет файлы: так файлы могут поменяться местами.
# Двоеточие в путях запрещено (9.8) — с файлом пользователя путь не совпадёт, а к концу
# отката таких путей не остаётся.
_REVERT_TEMP_PREFIX = ":revert:"
# Сколько путей назвать в тексте ошибки отката; все они — в details.files.
_CONFLICTS_IN_MESSAGE = 3


async def get_owned_changeset(
    session: AsyncSession, changeset_id: uuid.UUID, owner_id: uuid.UUID
) -> Changeset | None:
    """Changeset проекта владельца или None: чужой и несуществующий не различаются."""
    return await session.scalar(
        select(Changeset)
        .join(Project, Project.id == Changeset.project_id)
        .where(Changeset.id == changeset_id, Project.owner_id == owner_id)
    )


async def list_changesets(
    session: AsyncSession, project_id: uuid.UUID, *, before: uuid.UUID | None, limit: int
) -> tuple[list[Changeset], bool]:
    """Changesets проекта, в которых что-то записано, новые первыми, — не больше limit,
    и есть ли ещё. before — последний changeset предыдущей страницы; нет его в истории
    проекта — 422."""
    query = select(Changeset).where(
        Changeset.project_id == project_id,
        exists().where(FileRevision.changeset_id == Changeset.id),
    )
    if before is not None:
        cursor = await session.scalar(
            select(Changeset).where(Changeset.id == before, Changeset.project_id == project_id)
        )
        if cursor is None:
            raise request_error(["query", "before"], "Таких правок нет в истории проекта")
        query = query.where(
            tuple_(Changeset.created_at, Changeset.id)
            < tuple_(literal(cursor.created_at), literal(cursor.id, Uuid))
        )
    found = list(
        await session.scalars(
            query.order_by(Changeset.created_at.desc(), Changeset.id.desc()).limit(limit + 1)
        )
    )
    return found[:limit], len(found) > limit


async def revert_changeset(
    session: AsyncSession, writer: Writer, changeset: Changeset
) -> Changeset:
    """Возвращает файлы и папки changeset к виду до него и возвращает changeset отката.

    Откат — новый changeset автора writer с reverts_id (architecture.md 9.1). Всё или
    ничего: файл, который после changeset изменили, удалили или перенесли, или занятое
    место, куда нужно вернуть файл, — 409 revert_conflict со списком файлов. Если все
    файлы уже такие, как до changeset, — тоже 409, с пустым списком. Создание проекта
    и meta.tex — 403, проект станет больше 200 МБ — 413.
    """
    if changeset.author in NOT_REVERTED:
        raise AppError(ErrorCode.FORBIDDEN, NOT_REVERTED[changeset.author], 403)
    project_id, changeset_id = changeset.project_id, changeset.id
    async with _changing_files(session, writer, project_id) as change:
        change.reverts(changeset_id)
        plan = plan_revert(await changeset_segments(session, changeset_id))
        # Правки пользователя meta.tex не трогают, но если бы тронули — откат его не меняет.
        if any(segment.current_role == "generated" for segment in plan.files):
            raise _generated_file()
        plan.conflicts.extend(await _taken_by_others(session, project_id, plan))
        if plan.conflicts or plan.empty:
            raise _revert_conflict(plan.conflicts)
        added = sum((s.before.size or 0) - (s.current.size or 0) for s in plan.files)
        if added > 0 and await _project_size(session, project_id) + added > PROJECT_MAX_BYTES:
            raise _project_too_large()
        await _apply_revert(session, change, plan)
        if not change.written:
            # Остались только папки, которые и так на месте или не пусты.
            raise _revert_conflict([])
        reverted = await change.changeset()
        await change.save()
        await session.commit()
    await change.publish()
    return reverted


def _revert_conflict(conflicts: Sequence[tuple[str, RevertConflictReason]]) -> AppError:
    if not conflicts:
        return AppError(
            ErrorCode.REVERT_CONFLICT,
            "Откатывать нечего: файлы уже такие, как до этих правок",
            409,
            {"files": []},
        )
    paths = sorted({path for path, _ in conflicts})
    shown = ", ".join(paths[:_CONFLICTS_IN_MESSAGE])
    if len(paths) > _CONFLICTS_IN_MESSAGE:
        shown += f" и ещё {len(paths) - _CONFLICTS_IN_MESSAGE}"
    return AppError(
        ErrorCode.REVERT_CONFLICT,
        f"Откатить нельзя: после этих правок файлы изменились или их место занято: {shown}",
        409,
        {"files": [{"path": path, "reason": reason} for path, reason in sorted(conflicts)]},
    )


async def _taken_by_others(
    session: AsyncSession, project_id: uuid.UUID, plan: RevertPlan
) -> list[tuple[str, RevertConflictReason]]:
    """Места, куда откат вернёт файлы и папки, но где сейчас другой файл, — path_taken.

    Не мешают: сам этот файл, файл, который откат с этого места уберёт, папка, которую
    откатываемый changeset создал или перенёс сюда (откат её удалит или вернёт, если в ней
    не останется чужого), и папка на месте папки. Если папка всё же не уйдёт, а занятые
    папки над местом — это откат найдёт, когда будет возвращать файл.
    """
    targets = {
        segment.before.path: segment
        for segment in [*plan.files, *plan.folders]
        if segment.before.path is not None
    }
    if not targets:
        return []
    leaving = {s.file_id for s in [*plan.files, *plan.folders] if s.current.path != s.before.path}
    occupants = await session.execute(
        select(File.id, File.path, File.kind).where(
            File.project_id == project_id, File.path.in_(list(targets))
        )
    )
    taken: list[tuple[str, RevertConflictReason]] = []
    for occupant in occupants:
        segment = targets[occupant.path]
        if occupant.id == segment.file_id or occupant.id in leaving:
            continue
        if occupant.kind == "folder" and segment.is_folder:
            continue
        taken.append((occupant.path, "path_taken"))
    return taken


async def _apply_revert(session: AsyncSession, change: ProjectChange, plan: RevertPlan) -> None:
    """Применяет план отката. Порядок такой, чтобы файлы не мешали друг другу:

    1. удаляются файлы, которых до changeset не было;
    2. переносимые файлы уходят на временные пути — так два файла могут поменяться местами;
    3. удаляются опустевшие папки, созданные changeset: на их месте мог быть файл;
    4. удалённые папки создаются снова, перенесённые возвращаются, верхние — первыми;
    5. файлы возвращаются на прежние места с прежним содержимым;
    6. удаляются опустевшие папки, созданные changeset или оставшиеся там, куда он их
       перенёс, — те, что опустели после шагов 4 и 5.
    """
    existing = [s.file_id for s in plan.files if s.current.exists]
    if existing:
        await change.snapshot(File.id.in_(existing))
    removed = [s for s in plan.files if not s.before.exists and s.current.path is not None]
    if removed:
        await session.execute(delete(File).where(File.id.in_([s.file_id for s in removed])))
        for segment in removed:
            change.file_deleted(segment.current.path or "")
    restored = [s for s in plan.files if s.before.path is not None]
    moving = [s.file_id for s in restored if s.current.exists and s.current.path != s.before.path]
    if moving:
        await session.execute(
            update(File)
            .where(File.id.in_(moving))
            .values(path=func.concat(_REVERT_TEMP_PREFIX, cast(File.id, String)))
        )
    await _drop_empty_folders(session, change, [s for s in plan.folders if not s.before.exists])
    folders = [s for s in plan.folders if s.before.path is not None]
    for segment in sorted(folders, key=lambda s: (s.before.path or "").count("/")):
        await _restore_folder(session, change, segment)
    for segment in restored:
        await _restore_file(session, change, segment)
    await _drop_empty_folders(session, change, plan.folders)


async def _ensure_revert_parents(session: AsyncSession, change: ProjectChange, path: str) -> None:
    """Папки над местом, куда откат возвращает файл. На месте одной из них файл — конфликт."""
    try:
        await _ensure_folders(session, change, change.project_id, _parents(path))
    except AppError as error:
        if error.code != ErrorCode.ALREADY_EXISTS:
            raise
        raise _revert_conflict([(path, "path_taken")]) from None


async def _restore_file(session: AsyncSession, change: ProjectChange, segment: Segment) -> None:
    """Возвращает файл на прежнее место с прежним содержимым: текст копируется из ревизии
    в базе, у картинки возвращается ссылка на тот же blob."""
    path = segment.before.path
    assert path is not None
    project_id = change.project_id
    await _ensure_revert_parents(session, change, path)
    occupant = await session.scalar(
        select(File.id).where(File.project_id == project_id, File.path == path)
    )
    if occupant is not None and occupant != segment.file_id:
        raise _revert_conflict([(path, "path_taken")])
    role = role_for(path)
    revision = FileRevision
    content_changed = not segment.current_has_before_content
    version = change.next_version() if content_changed else segment.current_version
    if not segment.current.exists:
        # Удалённый файл возвращается с прежним id — история файла не рвётся.
        rows = select(
            revision.file_id,
            literal(project_id, Uuid),
            literal(path),
            revision.kind,
            literal(role),
            revision.content,
            revision.blob_sha256,
            revision.mime,
            revision.size,
            literal(version),
        ).where(revision.id == segment.revision_id)
        columns = ["id", "project_id", "path", "kind", "role", "content", "blob_sha256"]
        await session.execute(insert(File).from_select([*columns, "mime", "size", "version"], rows))
        await change.created([segment.file_id])
    elif content_changed:
        await session.execute(
            update(File)
            .where(
                File.id == segment.file_id,
                revision.file_id == File.id,
                revision.id == segment.revision_id,
            )
            .values(
                path=path,
                role=role,
                version=version,
                kind=revision.kind,
                content=revision.content,
                blob_sha256=revision.blob_sha256,
                mime=revision.mime,
                size=revision.size,
            )
        )
    else:
        await session.execute(
            update(File).where(File.id == segment.file_id).values(path=path, role=role)
        )
    if role == "material":
        # Другое содержимое — текст извлекается заново; тот же — извлечённый остаётся.
        sync = materials_service.mark_pending if content_changed else materials_service.keep_or_add
        change.materials_pending(await sync(session, [segment.file_id]))
    elif segment.current_role == "material":
        await materials_service.forget(session, [segment.file_id])
    if segment.current.path is not None and segment.current.path != path:
        change.file_moved(segment.current.path, path)
    if content_changed and version is not None:
        change.file_changed(path, version)


async def _restore_folder(session: AsyncSession, change: ProjectChange, segment: Segment) -> None:
    """Папка, удалённая или перенесённая changeset, — снова на прежнем месте.

    Там уже папка — ничего не нужно. Сама папка (тот же id) пуста — переносится обратно;
    в ней что-то есть — на прежнем месте создаётся новая, а эта остаётся.
    """
    path = segment.before.path
    assert path is not None
    project_id = change.project_id
    occupant = (
        await session.execute(
            select(File.kind).where(File.project_id == project_id, File.path == path)
        )
    ).one_or_none()
    if occupant is not None:
        if occupant.kind != "folder":
            raise _revert_conflict([(path, "path_taken")])
        return
    await _ensure_revert_parents(session, change, path)
    own = await session.scalar(select(File.path).where(File.id == segment.file_id))
    if own is not None and not await _has_children(session, project_id, own):
        await change.snapshot(File.id == segment.file_id)
        await session.execute(
            update(File).where(File.id == segment.file_id).values(path=path, role="source")
        )
        change.file_moved(own, path)
        return
    if own is None:
        session.add(
            File(id=segment.file_id, project_id=project_id, path=path, kind="folder", role="source")
        )
        await session.flush()
        await change.created([segment.file_id])
    else:
        await _ensure_folders(session, change, project_id, [path])
    folder = (await session.execute(_select_file(project_id, path))).scalar_one()
    change.file_changed(folder.path, folder.version)


async def _drop_empty_folders(
    session: AsyncSession, change: ProjectChange, folders: Sequence[Segment]
) -> None:
    """Удаляет папки changeset, которые не на прежнем месте и пусты: созданные им
    и оставшиеся там, куда он их перенёс. Глубокие — первыми: так опустеет и папка над ними.
    Папку, которую откат ставит на прежнее место другой папки, не трогает."""
    if not folders:
        return
    by_id = {segment.file_id: segment for segment in folders}
    wanted = {segment.before.path for segment in folders if segment.before.exists}
    rows = list(await session.execute(select(File.id, File.path).where(File.id.in_(list(by_id)))))
    for row in sorted(rows, key=lambda row: row.path.count("/"), reverse=True):
        if row.path == by_id[row.id].before.path or row.path in wanted:
            continue
        if await _has_children(session, change.project_id, row.path):
            continue
        await change.snapshot(File.id == row.id)
        await session.execute(delete(File).where(File.id == row.id))
        change.file_deleted(row.path)


async def _has_children(session: AsyncSession, project_id: uuid.UUID, folder: str) -> bool:
    child = await session.scalar(
        select(File.id).where(File.project_id == project_id, _in_folder(folder)).limit(1)
    )
    return child is not None
