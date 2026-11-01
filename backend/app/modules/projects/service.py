"""Проекты и их файлы. Другие модули работают с таблицами projects и files только здесь.

Каждый путь файла проходит validate_path (architecture.md 9.8), кто бы ни вызвал функцию.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.errors import AppError, ErrorCode
from app.modules.projects.models import File, Project
from app.modules.projects.paths import validate_path
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


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, FILE_NOT_FOUND_MESSAGE, 404)


def _parents(path: str) -> list[str]:
    """Папки над путём, от верхней: a/b/c.tex → [a, a/b]."""
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


async def _find(session: AsyncSession, project_id: uuid.UUID, path: str) -> File | None:
    return await session.scalar(
        select(File).where(File.project_id == project_id, File.path == path)
    )


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
    file = await session.scalar(
        select(File).where(File.project_id == project_id, File.path == path).with_for_update()
    )
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
        raise AppError(ErrorCode.ALREADY_EXISTS, "Такой файл уже есть", 409)

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
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        # Тот же файл в эту же секунду создал другой запрос.
        if getattr(error.orig, "pgcode", None) == _UNIQUE_VIOLATION:
            raise AppError(ErrorCode.ALREADY_EXISTS, "Такой файл уже есть", 409) from error
        raise
    return file, created
