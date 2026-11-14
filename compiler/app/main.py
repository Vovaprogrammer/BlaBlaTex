"""HTTP-сервис компиляции (architecture.md 9.7): на входе tar.gz проекта, на выходе tar.gz.

И запросы SyncTeX по файлу сборки: место в PDF ↔ строка файла проекта (synctex.py).
"""

import asyncio
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import IO, Annotated

import structlog
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.archive import (
    MAX_ARCHIVE_BYTES,
    MB,
    ArchiveError,
    extract_project,
    is_safe_relative_path,
    pack_result,
)
from app.errors import RequestFieldError, payload_too_large, register_error_handlers
from app.logging import configure_logging
from app.runner import JOB_PREFIX, OUT_DIR, SOURCE_DIR, Engine, RunResult, Status, run_latexmk
from app.synctex import MAX_SYNCTEX_BYTES, Box, Source, SyncTexTooLargeError
from app.synctex import edit as synctex_edit_query
from app.synctex import view as synctex_view_query
from app.version import SHARED_TEX_DIR, compiler_version

DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 120
# Больше сборок сразу не влезет в память: tmpfs /tmp и сами TeX делят mem_limit из compose.
MAX_PARALLEL_BUILDS = 2
# Запросы SyncTeX идут мимо очереди сборок, но тоже не все сразу: synctex держит в памяти
# весь файл, а сайт спрашивает позицию курсора часто.
MAX_PARALLEL_SYNCTEX = 2
SYNCTEX_PATHS = frozenset({"/synctex/edit", "/synctex/view"})
# Предел размера страницы PDF — 200 дюймов, в пунктах (1/72 дюйма).
MAX_COORDINATE = 14_400
# В текстовом файле до 2 МБ строк заведомо меньше.
MAX_LINE = 10_000_000
# Предел длины пути проекта (9.8).
MAX_PATH_LENGTH = 255
# latexmk передаёт имя главного файла в shell в двойных кавычках: обратная кавычка, «$»
# или «"» в нём выполнили бы команду. Поэтому — только буквы, цифры, пробел и «_ - . /».
_MAIN_NAME = re.compile(r"[\w\-. /]+\.tex")

log = structlog.get_logger()
router = APIRouter()


class SlotsMiddleware:
    """Не больше slots запросов сразу к адресам paths, остальные ждут своей очереди.

    Очередь ждёт до чтения тела запроса: архивы и файлы из очереди не копятся в tmpfs.
    """

    def __init__(self, app: ASGIApp, slots: int, paths: frozenset[str]) -> None:
        self.app = app
        self.slots = asyncio.Semaphore(slots)
        self.paths = paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in self.paths:
            await self.app(scope, receive, send)
            return
        async with self.slots:
            await self.app(scope, receive, send)


class BodyLimitMiddleware:
    """Обрывает запрос, как только тело превысило лимит, — не дожидаясь конца загрузки."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Размер известен заранее — отказываем сразу, ничего не читая.
        length = dict(scope["headers"]).get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_bytes:
            await payload_too_large()(scope, receive, send)
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
    """Живость сервиса и версия окружения, которую бэкенд кладёт в ключ кэша сборок."""
    version = await asyncio.to_thread(compiler_version, SHARED_TEX_DIR)
    return {"status": "ok", "version": version}


@router.post("/compile", response_class=Response)
async def compile_project(
    archive: Annotated[UploadFile, File(description="tar.gz с файлами проекта")],
    main: Annotated[str, Form(description="Главный .tex-файл, путь внутри архива")] = "main.tex",
    engine: Annotated[Engine, Form()] = "xelatex",
    timeout_s: Annotated[int, Form(ge=1, le=MAX_TIMEOUT_S)] = DEFAULT_TIMEOUT_S,
) -> Response:
    """Собирает проект. Ошибка LaTeX и таймаут — это 200 со статусом в result.json."""
    _check_main_path(main)
    job = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix=JOB_PREFIX))
    try:
        # Проект — в src/, вывод latexmk — рядом, вне папки, которую видит TeX.
        src, console = job / SOURCE_DIR, job / "latexmk.txt"
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


class EditResult(BaseModel):
    source: Source | None


class ViewResult(BaseModel):
    boxes: list[Box]


@router.post("/synctex/edit")
async def synctex_edit(
    synctex: Annotated[UploadFile, File(description="output.synctex.gz сборки")],
    page: Annotated[int, Form(ge=1, description="Страница PDF, от 1")],
    x: Annotated[float, Form(ge=0, le=MAX_COORDINATE, description="Пункты от левого края")],
    y: Annotated[float, Form(ge=0, le=MAX_COORDINATE, description="Пункты от верхнего края")],
) -> EditResult:
    """Что написано в месте страницы PDF. source: null — здесь нет текста студента."""
    _check_synctex_size(synctex)
    return EditResult(source=await synctex_edit_query(synctex.file, page, x, y))


@router.post("/synctex/view")
async def synctex_view(
    synctex: Annotated[UploadFile, File(description="output.synctex.gz сборки")],
    path: Annotated[str, Form(description="Путь файла в проекте")],
    line: Annotated[int, Form(ge=1, le=MAX_LINE, description="Номер строки, от 1")],
) -> ViewResult:
    """Где в PDF строка файла. boxes пустой — строки нет в PDF."""
    _check_view_path(path)
    _check_synctex_size(synctex)
    return ViewResult(boxes=await synctex_view_query(synctex.file, path, line))


def _check_synctex_size(synctex: UploadFile) -> None:
    if synctex.size is not None and synctex.size > MAX_SYNCTEX_BYTES:
        raise SyncTexTooLargeError(f"Файл SyncTeX больше {MAX_SYNCTEX_BYTES // MB} МБ")


def _check_view_path(path: str) -> None:
    # Двоеточие разделяет поля аргумента synctex -i строка:столбец:файл.
    if len(path) > MAX_PATH_LENGTH or ":" in path or not is_safe_relative_path(path):
        raise RequestFieldError(
            "path",
            "invalid_path",
            "path — относительный путь файла проекта без частей «.» и «..», без \\ и :",
        )


def _check_main_path(main: str) -> None:
    # Путь с «-» в начале latexmk принял бы за опцию, например -e с Perl-кодом.
    if main.startswith("-") or not _MAIN_NAME.fullmatch(main) or not is_safe_relative_path(main):
        raise RequestFieldError(
            "main",
            "invalid_main",
            "main — относительный путь к .tex-файлу внутри архива; "
            "в имени только буквы, цифры, пробел и _ - . /",
        )


def _unpack(archive: IO[bytes], src: Path, main: str) -> None:
    try:
        extract_project(archive, src)
    except ArchiveError as error:
        raise RequestFieldError("archive", "invalid_archive", str(error)) from error
    # Иначе старые out/main.pdf и out/main.fdb_latexmk из архива выдавались бы за новую сборку.
    if (src / OUT_DIR).exists():
        raise RequestFieldError(
            "archive", "reserved_path", f"Папка {OUT_DIR}/ занята: туда пишутся результаты сборки"
        )
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
    # Добавлены последними — значит, внешние: запрос сначала ждёт слот и только потом читается.
    # У сборок и у SyncTeX очереди свои: подсветка в PDF не ждёт минутную сборку.
    app.add_middleware(SlotsMiddleware, slots=MAX_PARALLEL_SYNCTEX, paths=SYNCTEX_PATHS)
    app.add_middleware(SlotsMiddleware, slots=MAX_PARALLEL_BUILDS, paths=frozenset({"/compile"}))
    app.include_router(router)
    return app


# Объект для uvicorn.
app = create_app()
