"""Проекты и их файлы. Другие модули работают с таблицами projects и files только здесь.

Каждый путь файла проходит validate_path (architecture.md 9.8), кто бы ни вызвал функцию.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql import ColumnElement

from app.core.errors import AppError, ErrorCode
from app.modules.projects.models import File, Project
from app.modules.projects.paths import (
    MAX_PATH_LENGTH,
    TEXT_FILE_EXTENSIONS,
    is_text_file_type,
    validate_path,
)
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate

# Шаблонов пока нет: эти значения модуль шаблонов (A1.2) возьмёт из template.yaml.
DEFAULT_KIND = "lab"
DEFAULT_TEMPLATE_VERSION = 1
DEFAULT_MAIN_FILE = "main.tex"
DEFAULT_ENGINE = "xelatex"

# Лимиты из 9.8 — в байтах (у текста — в UTF-8).
TEXT_FILE_MAX_BYTES = 2 * 1024 * 1024
PROJECT_MAX_BYTES = 200 * 1024 * 1024
TEXT_MIME = "text/plain"
PROJECT_NOT_FOUND_MESSAGE = "Проект не найден"
FILE_NOT_FOUND_MESSAGE = "Файл не найден"
PATH_NOT_FOUND_MESSAGE = "Файл или папка не найдены"
PATH_TAKEN_MESSAGE = "Файл или папка с таким путём уже есть"
# Документы из materials/ (методичку, задание) читает только ИИ — в сборку они не идут.
# Регистр расширения не важен.
MATERIAL_DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".pptx", ".xlsx")


async def create_project(
    session: AsyncSession, owner_id: uuid.UUID, data: ProjectCreate
) -> Project:
    """Создаёт пустой проект без файлов. Поля шаблона сохраняются как пришли, без проверки."""
    project = Project(
        owner_id=owner_id,
        title=data.title,
        kind=DEFAULT_KIND,
        template_slug=data.template_slug,
        template_version=DEFAULT_TEMPLATE_VERSION,
        fields=data.fields,
        main_file=DEFAULT_MAIN_FILE,
        engine=DEFAULT_ENGINE,
    )
    session.add(project)
    await session.commit()
    return project


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

    fields заменяются целиком. meta.tex пока не пересоздаётся — это сделает A1.2.
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


def _not_found(message: str = FILE_NOT_FOUND_MESSAGE) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, message, 404)


def _path_taken() -> AppError:
    return AppError(ErrorCode.ALREADY_EXISTS, PATH_TAKEN_MESSAGE, 409)


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


async def read_text_file(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Текстовый файл вместе с содержимым. Нет файла или это папка — 404."""
    file = await session.scalar(
        select(File).where(File.project_id == project_id, File.path == validate_path(path))
    )
    # Бинарные файлы появятся в B2.2 и будут отдаваться отдельно.
    if file is None or file.kind != "text":
        raise _not_found()
    return file


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
    проект станет больше 200 МБ — 413.
    """
    path = validate_path(path)
    size = len(content.encode())
    if size > TEXT_FILE_MAX_BYTES:
        raise file_too_large()
    # Postgres не хранит нулевой символ в тексте.
    if "\x00" in content:
        raise _invalid("В тексте не может быть нулевого символа")
    async with _changing_files(session, project_id):
        file = await _find(session, project_id, path)
        if file is not None and file.kind != "text":
            raise AppError(ErrorCode.ALREADY_EXISTS, "По этому пути уже есть папка", 409)
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
        used = await session.scalar(
            select(func.coalesce(func.sum(File.size), 0)).where(File.project_id == project_id)
        )
        if (used or 0) - (file.size if file else 0) + size > PROJECT_MAX_BYTES:
            raise AppError(
                ErrorCode.PAYLOAD_TOO_LARGE,
                f"Проект не может быть больше {PROJECT_MAX_BYTES // (1024 * 1024)} МБ. "
                "Удалите ненужные файлы.",
                413,
            )

        created = file is None
        if file is None:
            await _ensure_folders(session, project_id, _parents(path))
            file = File(
                project_id=project_id,
                path=path,
                kind="text",
                role="source",
                content=content,
                mime=TEXT_MIME,
                size=size,
            )
            session.add(file)
        else:
            file.content = content
            file.size = size
            file.version += 1
        await session.commit()
    return file, created


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
    Папки над новым путём создаются сами.
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
        is_folder = source.kind == "folder"
        # Файл «внутрь себя» отсекает _ensure_folders: на месте папки окажется файл — 409.
        if is_folder and to_path.startswith(from_path + "/"):
            raise _invalid("Нельзя переместить папку внутрь неё самой")
        if await _find(session, project_id, to_path) is not None:
            raise _path_taken()
        # Переименование не должно превращать текст в «картинку»; типы загрузок — B2.2.
        if source.kind == "text":
            _check_text_file_type(to_path)
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
            # Новый путь — новый префикс и остаток старого пути после «папка/».
            rest = func.substr(File.path, len(from_path) + 2)
            await session.execute(
                update(File)
                .where(File.project_id == project_id, _in_folder(from_path))
                .values(path=func.concat(to_path + "/", rest))
            )
        source.path = to_path
        await session.commit()
    return source


async def delete_path(session: AsyncSession, project_id: uuid.UUID, path: str) -> None:
    """Удаляет файл или папку со всем содержимым. Нет такого пути — 404."""
    path = validate_path(path)
    async with _changing_files(session, project_id):
        if await _find(session, project_id, path) is None:
            raise _not_found(PATH_NOT_FOUND_MESSAGE)
        await session.execute(
            delete(File).where(
                File.project_id == project_id, or_(File.path == path, _in_folder(path))
            )
        )
        await session.commit()
