"""HTTP-сервис компиляции (architecture.md 9.7): на входе tar.gz проекта, на выходе tar.gz."""

import asyncio
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import IO, Annotated

import structlog
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.archive import (
    MAX_ARCHIVE_BYTES,
    MB,
    ArchiveError,
    extract_project,
    is_safe_relative_path,
    pack_result,
)
from app.errors import RequestFieldError, register_error_handlers
from app.logging import configure_logging
from app.runner import OUT_DIR, Engine, RunResult, Status, run_latexmk

DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 120

log = structlog.get_logger()
router = APIRouter()


class BodyLimitMiddleware:
    """Обрывает запрос, как только тело превысило лимит, — не дожидаясь конца загрузки."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                # FastAPI пропускает HTTPException из разбора формы как есть.
                raise HTTPException(413)
            return message

        await self.app(scope, limited_receive, send)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/compile", response_class=Response)
async def compile_project(
    archive: Annotated[UploadFile, File(description="tar.gz с файлами проекта")],
    main: Annotated[str, Form(description="Главный .tex-файл, путь внутри архива")] = "main.tex",
    engine: Annotated[Engine, Form()] = "xelatex",
    timeout_s: Annotated[int, Form(ge=1, le=MAX_TIMEOUT_S)] = DEFAULT_TIMEOUT_S,
) -> Response:
    """Собирает проект. Ошибка LaTeX и таймаут — это 200 со статусом в result.json."""
    _check_main_path(main)
    job = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="job-"))
    try:
        # Проект — в src/, вывод latexmk — рядом, вне папки, которую видит TeX.
        src, console = job / "src", job / "latexmk.txt"
        await asyncio.to_thread(_unpack, archive.file, src, main)
        run = await run_latexmk(src, console, engine, main, timeout_s)
        body, status = await asyncio.to_thread(_pack, run, src / OUT_DIR, main, console)
    finally:
        await asyncio.to_thread(shutil.rmtree, job, True)
    log.info(
        "compile_finished",
        engine=engine,
        status=status,
        exit_code=run.exit_code,
        duration_ms=run.duration_ms,
        response_bytes=len(body),
    )
    return Response(body, media_type="application/gzip")


def _check_main_path(main: str) -> None:
    # Путь с «-» в начале latexmk принял бы за опцию, например -e с Perl-кодом.
    if main.startswith("-") or not main.endswith(".tex") or not is_safe_relative_path(main):
        raise RequestFieldError(
            "main", "invalid_main", "main — относительный путь к .tex-файлу внутри архива"
        )


def _unpack(archive: IO[bytes], src: Path, main: str) -> None:
    try:
        extract_project(archive, src)
    except ArchiveError as error:
        raise RequestFieldError("archive", "invalid_archive", str(error)) from error
    if not (src / main).is_file():
        raise RequestFieldError("main", "main_not_found", f"В архиве нет файла {main}")


def _pack(run: RunResult, out: Path, main: str, console: Path) -> tuple[bytes, Status]:
    stem = PurePosixPath(main).stem
    pdf, tex_log = out / f"{stem}.pdf", out / f"{stem}.log"
    status = run.status
    # latexmk может завершиться с кодом 0, не сделав PDF, — это не успех.
    if status == "ok" and not pdf.is_file():
        status = "error"
    result = {"status": status, "exit_code": run.exit_code, "duration_ms": run.duration_ms}
    files = {
        "output.pdf": pdf,
        # Если TeX не успел запуститься, его лога нет — отдаём вывод latexmk.
        "output.log": tex_log if tex_log.is_file() else console,
        "output.synctex.gz": out / f"{stem}.synctex.gz",
    }
    return pack_result(result, files), status


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="BlaBlaTex compiler", docs_url=None, redoc_url=None, openapi_url=None)
    register_error_handlers(app)
    # Запас 1 МБ — на заголовки multipart и остальные поля формы.
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_ARCHIVE_BYTES + MB)
    app.include_router(router)
    return app


# Объект для uvicorn.
app = create_app()
