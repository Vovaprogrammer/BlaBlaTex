"""Проекты и их файлы. Другие модули работают с таблицами projects и files только здесь.

Каждый путь файла проходит validate_path (architecture.md 9.8), кто бы ни вызвал функцию.
"""

import uuid

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql import ColumnElement

from app.core.errors import AppError, ErrorCode
from app.modules.projects.models import File, Project
from app.modules.projects.paths import MAX_PATH_LENGTH, validate_path
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate

# Шаблонов пока нет: эти значения модуль шаблонов (A1.2) возьмёт из template.yaml.
DEFAULT_KIND = "lab"
DEFAULT_TEMPLATE_VERSION = 1
DEFAULT_MAIN_FILE = "main.tex"
DEFAULT_ENGINE = "xelatex"

# Лимит текстового файла из 9.8 — в байтах UTF-8.
TEXT_FILE_MAX_BYTES = 2 * 1024 * 1024
TEXT_MIME = "text/plain"
FILE_NOT_FOUND_MESSAGE = "Файл не найден"
PATH_NOT_FOUND_MESSAGE = "Файл или папка не найдены"
PATH_TAKEN_MESSAGE = "Файл или папка с таким путём уже есть"
# SQLSTATE «нарушена уникальность».
_UNIQUE_VIOLATION = "23505"


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


async def _find(
    session: AsyncSession, project_id: uuid.UUID, path: str, *, lock: bool = False
) -> File | None:
    """Файл или папка по пути. lock — заблокировать строку до коммита."""
    query = select(File).where(File.project_id == project_id, File.path == path)
    return await session.scalar(query.with_for_update() if lock else query)


async def _commit(session: AsyncSession) -> None:
    """Коммит. Если тот же путь в это же время занял другой запрос — 409."""
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        if getattr(error.orig, "pgcode", None) == _UNIQUE_VIOLATION:
            raise _path_taken() from error
        raise


async def _ensure_folders(session: AsyncSession, project_id: uuid.UUID, paths: list[str]) -> None:
    """Создаёт недостающие папки. Если на месте одной из них уже файл — 409.

    Изменения не коммитит; при ошибке откатывает транзакцию.
    """
    if not paths:
        return
    rows = [
        {"project_id": project_id, "path": path, "kind": "folder", "role": "source"}
        for path in paths
    ]
    # Уже существующие папки пропускаются; так же пропадает и гонка двух запросов.
    await session.execute(
        insert(File).values(rows).on_conflict_do_nothing(index_elements=["project_id", "path"])
    )
    clash = await session.scalar(
        select(File.path)
        .where(File.project_id == project_id, File.path.in_(paths), File.kind != "folder")
        .limit(1)
    )
    if clash is not None:
        await session.rollback()
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


async def read_text_file(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Текстовый файл вместе с содержимым. Нет файла или это папка — 404."""
    file = await _find(session, project_id, validate_path(path))
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
    файл уже есть — 409. Промежуточные папки создаются сами.
    """
    path = validate_path(path)
    size = len(content.encode())
    if size > TEXT_FILE_MAX_BYTES:
        raise file_too_large()
    # Строка блокируется до коммита: два одновременных сохранения с одной версией
    # не пройдут проверку оба — второе дождётся первого и увидит новую версию.
    file = await _find(session, project_id, path, lock=True)
    if file is not None and file.kind != "text":
        raise AppError(ErrorCode.ALREADY_EXISTS, "По этому пути уже есть папка", 409)
    if expected_version is not None and (file is None or file.version != expected_version):
        raise AppError(
            ErrorCode.FILE_CONFLICT,
            "Файл изменён в другом месте" if file else "Файл удалён в другом месте",
            412,
            {"current_version": file.version if file else None},
        )
    if create_only and file is not None:
        raise _path_taken()

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
    await _commit(session)
    return file, created


async def create_folder(session: AsyncSession, project_id: uuid.UUID, path: str) -> File:
    """Создаёт папку вместе с недостающими папками над ней. Путь уже занят — 409."""
    path = validate_path(path)
    if await _find(session, project_id, path) is not None:
        raise _path_taken()
    await _ensure_folders(session, project_id, [*_parents(path), path])
    await session.commit()
    folder = await _find(session, project_id, path)
    assert folder is not None  # только что создана в этой же сессии
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
    source = await _find(session, project_id, from_path, lock=True)
    if source is None:
        raise _not_found(PATH_NOT_FOUND_MESSAGE)
    if to_path == from_path:
        return source
    if to_path.startswith(from_path + "/"):
        raise _invalid("Нельзя переместить папку внутрь неё самой")
    if await _find(session, project_id, to_path) is not None:
        raise _path_taken()
    if source.kind == "folder":
        longest = await session.scalar(
            select(func.max(func.char_length(File.path))).where(
                File.project_id == project_id, _in_folder(from_path)
            )
        )
        if longest is not None and longest - len(from_path) + len(to_path) > MAX_PATH_LENGTH:
            raise _invalid(f"Путь вложенного файла станет длиннее {MAX_PATH_LENGTH} символов")

    await _ensure_folders(session, project_id, _parents(to_path))
    if source.kind == "folder":
        # Новый путь — новый префикс и остаток старого пути после «папка/».
        rest = func.substr(File.path, len(from_path) + 2)
        await session.execute(
            update(File)
            .where(File.project_id == project_id, _in_folder(from_path))
            .values(path=func.concat(to_path + "/", rest))
        )
    source.path = to_path
    await _commit(session)
    return source


async def delete_path(session: AsyncSession, project_id: uuid.UUID, path: str) -> None:
    """Удаляет файл или папку со всем содержимым. Нет такого пути — 404."""
    path = validate_path(path)
    if await _find(session, project_id, path) is None:
        raise _not_found(PATH_NOT_FOUND_MESSAGE)
    await session.execute(
        delete(File).where(File.project_id == project_id, or_(File.path == path, _in_folder(path)))
    )
    await session.commit()
