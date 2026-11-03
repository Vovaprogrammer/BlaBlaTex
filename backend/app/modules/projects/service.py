"""Проекты и их файлы. Другие модули работают с таблицами projects и files только здесь.

Каждый путь файла проходит validate_path (architecture.md 9.8), кто бы ни вызвал функцию.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import BinaryIO, Literal

import structlog
from sqlalchemy import Select, and_, case, delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql import ColumnElement

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.storage import BlobNotFoundError, Storage
from app.modules.materials import service as materials_service
from app.modules.projects import filetypes
from app.modules.projects.models import File, Project
from app.modules.projects.paths import (
    BINARY_FILE_TYPES,
    MAX_PATH_LENGTH,
    TEXT_FILE_EXTENSIONS,
    InvalidPathError,
    is_material_path,
    is_text_file_type,
    validate_path,
)
from app.modules.projects.schemas import Engine, FileRole, ProjectKind, ProjectUpdate

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
PROJECT_NOT_FOUND_MESSAGE = "Проект не найден"
FILE_NOT_FOUND_MESSAGE = "Файл не найден"
PATH_NOT_FOUND_MESSAGE = "Файл или папка не найдены"
PATH_TAKEN_MESSAGE = "Файл или папка с таким путём уже есть"
GENERATED_FILE_MESSAGE = "Файл создаётся автоматически"
# Документы из materials/ (методичку, задание) читает только ИИ — в сборку они не идут.
# Регистр расширения не важен.
MATERIAL_DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".pptx", ".xlsx")


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
            file_role = _role_for(path) if role == "source" else role
            checked[path] = (content, _check_text(content), file_role)
    if sum(size for _, size, _ in checked.values()) > PROJECT_MAX_BYTES:
        raise _project_too_large()
    project = Project(owner_id=owner_id, **asdict(new))
    session.add(project)
    # Строка проекта нужна в базе до папок: их вставка ссылается на project_id.
    await session.flush()
    folders = sorted({folder for path in checked for folder in _parents(path)})
    await _ensure_folders(session, project.id, folders)
    created = [
        File(
            project_id=project.id,
            path=path,
            kind="text",
            role=role,
            content=content,
            mime=TEXT_MIME,
            size=size,
        )
        for path, (content, size, role) in checked.items()
    ]
    session.add_all(created)
    # Строки material_text ссылаются на файлы: файлы — в базу раньше.
    await session.flush()
    await materials_service.mark_pending(
        session, [file.id for file in created if file.role == "material"]
    )
    await session.commit()
    return project


async def write_generated_file(
    session: AsyncSession, project_id: uuid.UUID, path: str, content: str
) -> None:
    """Пишет файл role=generated (meta.tex): создаёт его или заменяет текст.

    Коммит — за вызывающим: файл пересоздаётся вместе с полями проекта или профилем,
    в их транзакции. Проект блокируется, как при любой записи файлов, но не поднимается
    в списке — сам пользователь его не менял. Текст тот же — файл не трогается и версия
    не растёт. Проекта уже нет или по пути папка — файл не пишется: из-за одного
    такого проекта не должно падать сохранение профиля.
    """
    path = validate_path(path)
    size = _check_text(content)
    locked = await session.scalar(
        select(Project.id).where(Project.id == project_id).with_for_update()
    )
    if locked is None:
        return
    file = await session.scalar(
        select(File).where(File.project_id == project_id, File.path == path)
    )
    if file is None:
        await _ensure_folders(session, project_id, _parents(path))
        session.add(
            File(
                project_id=project_id,
                path=path,
                kind="text",
                role="generated",
                content=content,
                mime=TEXT_MIME,
                size=size,
            )
        )
    elif file.kind != "text":
        logger.warning("generated_file_skipped", project_id=str(project_id), path=path)
    elif file.content != content or file.role != "generated":
        # Файл с таким именем мог создать сам пользователь — теперь он генерируется.
        file.content = content
        file.size = size
        file.role = "generated"
        file.version += 1


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


async def update_project(session: AsyncSession, project: Project, data: ProjectUpdate) -> Project:
    """Меняет только переданные поля; null — то же, что поле не передано.

    fields заменяются целиком; по манифесту шаблона их проверяет модуль шаблонов.
    """
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(project, field, value)
    await session.commit()
    return project


async def delete_project(session: AsyncSession, project: Project) -> None:
    """Удаляет проект; его файлы база удаляет сама (ON DELETE CASCADE)."""
    await session.delete(project)
    await session.commit()


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


def _role_for(path: str) -> FileRole:
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


async def _lock_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Начало любого изменения файлов: блокирует строку проекта до коммита.

    Изменения файлов одного проекта идут по очереди: проверка версии, «путь свободен»
    и перенос папки не пересекутся с другим запросом. Заодно проект поднимается
    в списке — правка файла тоже его изменение. Проект успели удалить — 404.
    Порядок блокировок тот же, что у удаления проекта: сначала проект, потом файлы.
    """
    result = await session.execute(
        update(Project).where(Project.id == project_id).values(updated_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        raise AppError(ErrorCode.NOT_FOUND, PROJECT_NOT_FOUND_MESSAGE, 404)


@asynccontextmanager
async def _changing_files(session: AsyncSession, project_id: uuid.UUID) -> AsyncIterator[None]:
    """Изменение файлов проекта: блокирует проект, а при любой ошибке откатывает транзакцию.

    Без отката блокировка и соединение жили бы до закрытия сессии. В HTTP это сразу после
    ответа, а агент (этап 2) после ошибки инструмента продолжает с той же сессией — и все
    правки проекта ждали бы его. После отката загруженные объекты сессии сброшены:
    подгрузить их заново в async нельзя, поэтому после ошибки работают только с id.
    """
    try:
        await _lock_project(session, project_id)
        yield
    except Exception:
        await session.rollback()
        raise


async def _ensure_folders(session: AsyncSession, project_id: uuid.UUID, paths: list[str]) -> None:
    """Создаёт недостающие папки. Если на месте одной из них уже файл — 409.

    Изменения не коммитит и вызывается внутри _changing_files: при ошибке тот откатит
    и уже вставленные папки.
    """
    if not paths:
        return
    rows = [
        {"project_id": project_id, "path": path, "kind": "folder", "role": "source"}
        for path in paths
    ]
    # Уже существующие папки пропускаются.
    await session.execute(
        insert(File).values(rows).on_conflict_do_nothing(index_elements=["project_id", "path"])
    )
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
    is_document = or_(
        *(func.lower(File.path).endswith(ext) for ext in MATERIAL_DOCUMENT_EXTENSIONS)
    )
    result = await session.scalars(
        select(File)
        .where(
            File.project_id == project_id,
            File.kind != "folder",
            or_(
                File.role.in_(("source", "generated")),
                and_(File.role == "material", ~is_document),
            ),
        )
        .order_by(File.path)
    )
    return list(result)


async def read_file(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Файл вместе с содержимым: у текстового — текст, у бинарного — sha256 его blob'а
    в Storage (открывает open_binary). Нет файла или это папка — 404."""
    file = await session.scalar(
        select(File).where(File.project_id == project_id, File.path == validate_path(path))
    )
    if file is None or file.kind == "folder":
        raise _not_found()
    return file


async def read_text_file(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Текстовый файл вместе с содержимым. Нет файла, это папка или бинарный файл — 404."""
    file = await read_file(session, project_id, path)
    if file.kind != "text":
        raise _not_found()
    return file


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
    проект станет больше 200 МБ — 413. Файл role=generated — 403 (9.6).
    """
    path = validate_path(path)
    size = _check_text(content)
    async with _changing_files(session, project_id):
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
            await _ensure_folders(session, project_id, _parents(path))
            file = File(
                project_id=project_id,
                path=path,
                kind="text",
                role=_role_for(path),
                content=content,
                mime=TEXT_MIME,
                size=size,
            )
            session.add(file)
        else:
            file.content = content
            file.size = size
            file.version += 1
        if file.role == "material":
            # Новый материал или новый текст материала: извлечь заново (раздел 5).
            await session.flush()
            await materials_service.mark_pending(session, [file.id])
        await session.commit()
    return file, created


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
    async with _changing_files(session, project_id):
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
        await _ensure_folders(session, project_id, sorted(folders))
        replaced = sum(file.size for file in existing.values())
        added = sum(upload.size for upload in uploads)
        if await _project_size(session, project_id) - replaced + added > PROJECT_MAX_BYTES:
            raise _project_too_large()

        saved = [
            await _save_upload(session, storage, project_id, upload, existing.get(upload.path))
            for upload in uploads
        ]
        # И новый материал, и загруженный заново — снова в очередь на извлечение текста.
        await materials_service.mark_pending(
            session, [file.id for file in saved if file.role == "material"]
        )
        await session.commit()
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
    project_id: uuid.UUID,
    upload: CheckedUpload,
    file: File | None,
) -> File:
    """Записывает один файл загрузки: новый или поверх старого. Коммит — за вызывающим."""
    if file is None:
        file = File(project_id=project_id, path=upload.path)
        session.add(file)
    else:
        file.version += 1
    file.kind, file.mime, file.size = upload.kind, upload.mime, upload.size
    file.role = _role_for(upload.path)
    if upload.kind == "text":
        file.content = await asyncio.to_thread(_read_upload_text, upload.path, upload.source)
        file.blob_sha256 = None
    else:
        file.content = None
        file.blob_sha256 = await storage.put_file(upload.source)
    await session.flush()
    if upload.kind == "text":
        # Текст уже в базе: объект его больше не держит, память не копится от файла к файлу.
        session.expire(file, ["content"])
    return file


async def create_folder(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Создаёт папку вместе с недостающими папками над ней. Путь уже занят — 409."""
    path = validate_path(path)
    async with _changing_files(session, project_id):
        if await _find(session, project_id, path) is not None:
            raise _path_taken()
        await _ensure_folders(session, project_id, [*_parents(path), path])
        folder = (await session.execute(_select_file(project_id, path))).scalar_one()
        await session.commit()
    return folder


async def move_path(
    session: AsyncSession, project_id: uuid.UUID, from_path: str, to_path: str
) -> File:
    """Переносит или переименовывает файл или папку вместе со всем содержимым.

    Пути вложенных файлов меняются одним UPDATE в той же транзакции. Версии не меняются:
    версия — про содержимое, и открытый в редакторе файл сохранится без ложного конфликта.
    Роль — по новому пути (9.8): перенесённое в materials/ становится материалом, из неё —
    обычным файлом. Папки над новым путём создаются сами. Файл role=generated и папку
    с ним — 403 (9.6).
    """
    from_path, to_path = validate_path(from_path), validate_path(to_path)
    if to_path == from_path:
        # Перемещать нечего, и блокировать проект незачем.
        source = await _find(session, project_id, from_path)
        if source is None:
            raise _not_found(PATH_NOT_FOUND_MESSAGE)
        return source
    async with _changing_files(session, project_id):
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

        await _ensure_folders(session, project_id, _parents(to_path))
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
                        (File.kind == "folder", File.role), else_=literal(_role_for(to_path + "/"))
                    ),
                )
            )
        else:
            source.role = _role_for(to_path)
        source.path = to_path
        await _sync_moved_materials(session, project_id, source, to_path)
        await session.commit()
    return source


async def _sync_moved_materials(
    session: AsyncSession, project_id: uuid.UUID, source: File, to_path: str
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
        await materials_service.keep_or_add(session, moved)
    else:
        await materials_service.forget(session, moved)


async def delete_path(session: AsyncSession, project_id: uuid.UUID, path: str) -> None:
    """Удаляет файл или папку со всем содержимым. Нет такого пути — 404.

    Файл role=generated и папку с ним — 403 (9.6). Содержимое бинарных файлов остаётся
    в Storage: на него сошлются ревизии (B2.5), а тот же blob бывает и у других файлов.
    Неиспользуемые blob'ы удаляет очистка хранилища (B3.3).
    """
    path = validate_path(path)
    async with _changing_files(session, project_id):
        target = await _find(session, project_id, path)
        if target is None:
            raise _not_found(PATH_NOT_FOUND_MESSAGE)
        await _reject_generated(session, target)
        await session.execute(
            delete(File).where(
                File.project_id == project_id, or_(File.path == path, _in_folder(path))
            )
        )
        await session.commit()
