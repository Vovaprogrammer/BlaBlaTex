"""Сборки проекта и их артефакты (architecture.md 9.1). Логика — в service.py."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse

from app.core.db import DbSession
from app.core.errors import TEXT_CONTENT, AppError, ErrorCode
from app.core.storage import BlobNotFoundError, StorageDep
from app.modules.builds import service, tasks
from app.modules.builds.dependencies import BuildEnqueue, OwnedBuild
from app.modules.builds.models import Build
from app.modules.builds.schemas import BuildError, BuildOut
from app.modules.projects.dependencies import OwnedProject

router = APIRouter(tags=["builds"])

# Лог и PDF содержат текст пользователя: браузер не должен угадывать по нему тип
# и открывать, например, лог как HTML.
_NO_SNIFF = {"X-Content-Type-Options": "nosniff"}


def _build_out(build: Build) -> BuildOut:
    errors = [BuildError.model_validate(error) for error in build.errors]
    return BuildOut(
        id=build.id,
        project_id=build.project_id,
        status=build.status,
        engine=build.engine,
        pages=build.pages,
        duration_ms=build.duration_ms,
        warnings_count=sum(error.severity == "warning" for error in errors),
        errors=errors,
        has_pdf=build.pdf_sha256 is not None,
        created_at=build.created_at,
    )


async def _artifact(
    storage: StorageDep,
    sha256: str | None,
    *,
    missing: str,
    media_type: str,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """Файл сборки из Storage потоком: PDF до 50 МБ не читается в память целиком."""
    if sha256 is None:
        raise AppError(ErrorCode.NOT_FOUND, missing, 404)
    try:
        stream = await storage.open_stream(sha256)
    except BlobNotFoundError:
        # Хранилище очистили (например, в dev) — помогает только новая сборка.
        raise AppError(
            ErrorCode.NOT_FOUND, "Файл сборки не найден. Соберите проект ещё раз.", 404
        ) from None
    return StreamingResponse(
        stream, media_type=media_type, headers={**_NO_SNIFF, **(headers or {})}
    )


@router.post(
    "/projects/{pid}/builds",
    status_code=202,
    response_description="Сборка в очереди. Итог — GET /builds/{bid} или событие build.finished",
)
async def start_build(project: OwnedProject, session: DbSession, enqueue: BuildEnqueue) -> BuildOut:
    """Ставит сборку в очередь и сразу отвечает; собирает воркер (architecture.md 9.1).

    Пока сборка проекта ждёт в очереди, повторный запрос возвращает её же. Итог —
    статус сборки: ошибки LaTeX и недоступный компилятор — это status=error и список
    errors, а не HTTP-ошибка. Очередь недоступна — 500, сборка не создаётся.
    """
    build = await tasks.request_build(session, project, enqueue)
    return _build_out(build)


@router.get("/projects/{pid}/builds/latest")
async def latest_build(
    project: OwnedProject,
    session: DbSession,
    status: Annotated[
        Literal["ok"] | None,
        Query(description="ok — последняя успешная сборка, её PDF виден и после неудачной"),
    ] = None,
) -> BuildOut:
    """Последняя сборка проекта; 404, если сборок ещё не было. С status=ok — последняя
    успешная; 404, если успешных ещё не было."""
    build = await service.latest_build(session, project.id, status=status)
    if build is None:
        message = "Удачных сборок ещё не было" if status == "ok" else "Проект ещё не собирали"
        raise AppError(ErrorCode.NOT_FOUND, message, 404)
    return _build_out(build)


@router.get("/builds/{bid}")
async def get_build(build: OwnedBuild) -> BuildOut:
    return _build_out(build)


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
async def build_pdf(build: OwnedBuild, storage: StorageDep) -> Response:
    """PDF сборки; у сборки с ошибкой его нет — 404."""
    return await _artifact(
        storage,
        build.pdf_sha256,
        missing="У этой сборки нет PDF",
        media_type="application/pdf",
        # inline — открыть в браузере; имя — для «Сохранить как».
        headers={"Content-Disposition": f'inline; filename="build-{build.id}.pdf"'},
    )


@router.get(
    "/builds/{bid}/log",
    response_class=Response,
    responses={200: {"description": "Полный лог LaTeX", "content": TEXT_CONTENT}},
)
async def build_log(build: OwnedBuild, storage: StorageDep) -> Response:
    """Полный лог LaTeX как есть; нет лога, если до компилятора дело не дошло — 404."""
    return await _artifact(
        storage,
        build.log_sha256,
        missing="У этой сборки нет лога: проект не дошёл до компилятора",
        media_type="text/plain; charset=utf-8",
    )
