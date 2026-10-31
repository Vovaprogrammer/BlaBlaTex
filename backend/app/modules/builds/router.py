"""Сборки проекта и их артефакты. Пока заглушки: логику добавит B1.5."""

from uuid import UUID

from fastapi import APIRouter, Response

from app.core.errors import TEXT_CONTENT, not_implemented
from app.modules.builds.schemas import BuildOut

router = APIRouter(tags=["builds"])


@router.post("/projects/{pid}/builds", status_code=201)
async def start_build(pid: UUID) -> BuildOut:
    """Собирает PDF. На этапе 1 отвечает после окончания сборки.

    Ошибки LaTeX — это не HTTP-ошибка, а status=error и список errors.
    """
    raise not_implemented()


@router.get("/projects/{pid}/builds/latest")
async def latest_build(pid: UUID) -> BuildOut:
    """Последняя сборка проекта; 404, если сборок ещё не было."""
    raise not_implemented()


@router.get("/builds/{bid}")
async def get_build(bid: UUID) -> BuildOut:
    raise not_implemented()


@router.get(
    "/builds/{bid}/pdf",
    response_class=Response,
    responses={
        200: {
            "description": "PDF сборки",
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def build_pdf(bid: UUID) -> Response:
    raise not_implemented()


@router.get(
    "/builds/{bid}/log",
    response_class=Response,
    responses={200: {"description": "Полный лог LaTeX", "content": TEXT_CONTENT}},
)
async def build_log(bid: UUID) -> Response:
    raise not_implemented()
