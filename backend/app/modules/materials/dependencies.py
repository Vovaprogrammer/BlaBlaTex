"""HTTP-часть материалов: материал проекта текущего пользователя по пути."""

from typing import Annotated

from fastapi import Depends, Query

from app.core.db import DbSession
from app.core.errors import AppError, ErrorCode
from app.modules.projects import service as projects_service
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.models import File
from app.modules.projects.schemas import FilePath

MATERIAL_NOT_FOUND_MESSAGE = "Материал не найден"


async def get_owned_material(
    project: OwnedProject,
    session: DbSession,
    path: Annotated[FilePath, Query(description="Путь материала, например materials/task.pdf")],
) -> File:
    """Файл из materials/ проекта текущего пользователя. Чужой проект, нет файла, папка
    или файл не из materials/ — 404; путь нарушает 9.8 — 422."""
    file = await projects_service.find_file(session, project.id, path)
    if file is None or file.kind == "folder" or file.role != "material":
        raise AppError(ErrorCode.NOT_FOUND, MATERIAL_NOT_FOUND_MESSAGE, 404)
    return file


OwnedMaterial = Annotated[File, Depends(get_owned_material)]
