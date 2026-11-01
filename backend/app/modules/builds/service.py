"""Сборки: файлы проекта → архив → компилятор → артефакты в Storage и строка в builds.

На этапе 1 сборка синхронная: run_build возвращается, когда компилятор ответил.
Файлы проекта модуль читает только через сервис projects.
"""

import asyncio
import hashlib
import io
import json
import re
import tarfile
import time
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import INTERNAL_MESSAGE, AppError, ErrorCode
from app.core.storage import Storage
from app.modules.builds.compiler import (
    BUILD_TIMEOUT_S,
    CompilerClient,
    CompilerError,
    CompileResult,
    CompilerRejectedError,
    CompilerUnavailableError,
)
from app.modules.builds.log_parser import parse_log
from app.modules.builds.models import Build
from app.modules.builds.schemas import BuildError
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from app.modules.projects.schemas import Engine

logger = structlog.get_logger(__name__)

MB = 1024 * 1024
# PDF — до 50 МБ (9.8).
MAX_PDF_BYTES = 50 * MB
# Лимиты компилятора на архив (9.7): больше он не примет.
MAX_INPUT_BYTES = 200 * MB
MAX_INPUT_FILES = 10_000
# Правило компилятора для имени главного файла (9.7): latexmk передаёт его через shell.
_MAIN_NAME = re.compile(r"[\w\-. /]+\.tex")
# Папка, куда компилятор пишет результаты сборки; в архиве её быть не должно (9.7).
OUT_DIR = "out"

COMPILER_UNAVAILABLE_MESSAGE = "Сервис сборки сейчас недоступен. Попробуйте через минуту."


@dataclass(frozen=True)
class BuildInput:
    """Файл, который уходит в сборку. Текст уже в памяти, бинарный читается из Storage."""

    path: str
    sha256: str
    text: bytes | None


async def run_build(
    session: AsyncSession, storage: Storage, compiler: CompilerClient, project: Project
) -> Build:
    """Собирает проект и сохраняет сборку.

    Ошибки LaTeX, таймаут и проблемы проекта вроде отсутствующего главного файла —
    это сборка со status=error или timeout, а не исключение. Исключение (AppError 500) —
    только если компилятор недоступен: тогда сборка не сохраняется.
    """
    # Время начала, а не окончания: из двух сборок подряд последней будет начатая позже,
    # даже если первая закончится после неё, — она собирала более свежие файлы.
    started_at = datetime.now(UTC)
    files = await projects_service.list_build_files(session, project.id)
    await _release_connection(session)

    problem = find_input_problem(files, project.main_file)
    if problem is not None:
        build = Build(
            project_id=project.id,
            status="error",
            engine=project.engine,
            errors=[problem.model_dump()],
            created_at=started_at,
        )
        return await _save(session, build, cached=False)

    inputs = [_build_input(file) for file in files]
    version = await _call_compiler(project.id, compiler.version())
    key = inputs_hash(inputs, engine=project.engine, main=project.main_file, version=version)

    cached = await _find_cached(session, storage, project.id, key)
    if cached is not None:
        # Новая строка с теми же файлами: так «последняя сборка» — всегда последняя
        # нажатая, а файлы в Storage не копируются — они лежат по sha256.
        build = Build(
            project_id=project.id,
            status="ok",
            engine=project.engine,
            inputs_hash=key,
            pdf_sha256=cached.pdf_sha256,
            log_sha256=cached.log_sha256,
            synctex_sha256=cached.synctex_sha256,
            errors=list(cached.errors),
            pages=cached.pages,
            duration_ms=cached.duration_ms,
            created_at=started_at,
        )
        return await _save(session, build, cached=True)
    await _release_connection(session)

    archive = await _pack(storage, inputs)
    result = await _call_compiler(
        project.id, compiler.compile(archive, main=project.main_file, engine=project.engine)
    )
    # Исходники — для файлов из лога и контекста вокруг ошибок.
    sources = {file.path: file.content for file in files if file.content is not None}
    build = await _store_result(storage, result, sources)
    build.project_id = project.id
    build.engine = project.engine
    build.inputs_hash = key
    build.created_at = started_at
    return await _save(session, build, cached=False)


def find_input_problem(files: list[File], main: str) -> BuildError | None:
    """Проблема проекта, из-за которой компилятор его не примет (9.7), или None.

    Проверяется до вызова компилятора, чтобы показать понятную ошибку там же, где
    ошибки LaTeX, — её увидит и пользователь, и ИИ-агент.
    """
    if main.startswith("-") or not _MAIN_NAME.fullmatch(main):
        return _problem(
            f"В имени главного файла «{main}» есть недопустимые символы. "
            "Можно только буквы, цифры, пробел и _ - . /"
        )
    if not any(file.path == main and file.kind == "text" for file in files):
        return _problem(f"В проекте нет главного файла {main}. Создайте его или верните удалённый.")
    if any(file.path == OUT_DIR or file.path.startswith(f"{OUT_DIR}/") for file in files):
        return _problem(
            f"Папка {OUT_DIR}/ в корне проекта занята: туда сборка пишет результаты. "
            f"Переименуйте её, например в output/."
        )
    if len(files) > MAX_INPUT_FILES or sum(file.size for file in files) > MAX_INPUT_BYTES:
        return _problem(
            f"Проект слишком большой для сборки: больше {MAX_INPUT_BYTES // MB} МБ "
            f"или {MAX_INPUT_FILES} файлов."
        )
    return None


def inputs_hash(inputs: list[BuildInput], *, engine: Engine, main: str, version: str) -> str:
    """Ключ кэша (architecture.md 6): файлы (путь и sha256), движок, главный файл и версия
    компилятора. Порядок файлов не важен."""
    payload = {
        "files": sorted((item.path, item.sha256) for item in inputs),
        "engine": engine,
        "main": main,
        "compiler": version,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def pack_project(files: list[tuple[str, bytes]]) -> bytes:
    """tar.gz для компилятора: только обычные файлы, папки следуют из путей."""
    buffer = io.BytesIO()
    now = int(time.time())
    # Картинки уже сжаты, а текст и так маленький: сильнее сжимать — только тратить процессор.
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=1) as tar:
        for path, data in files:
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = now
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _problem(message: str) -> BuildError:
    return BuildError(file=None, line=None, message=message, context="", severity="error")


def _build_input(file: File) -> BuildInput:
    if file.kind == "text":
        text = (file.content or "").encode()
        return BuildInput(file.path, hashlib.sha256(text).hexdigest(), text)
    # Бинарный файл: в files лежит только sha256 содержимого из Storage.
    assert file.blob_sha256 is not None
    return BuildInput(file.path, file.blob_sha256, None)


async def _release_connection(session: AsyncSession) -> None:
    """Завершает транзакцию, и соединение возвращается в пул.

    Сборка с очередью идёт до нескольких минут — держать всё это время соединение из
    общего пула нельзя. Именно commit, а не rollback: rollback сбросил бы загруженные
    объекты, а подгрузить их заново в async нельзя.
    """
    await session.commit()


async def _find_cached(
    session: AsyncSession, storage: Storage, project_id: uuid.UUID, key: str
) -> Build | None:
    """Последняя успешная сборка проекта с тем же ключом, если её PDF ещё в Storage."""
    build = await session.scalar(
        select(Build)
        .where(Build.project_id == project_id, Build.inputs_hash == key, Build.status == "ok")
        .order_by(Build.created_at.desc())
        .limit(1)
    )
    if build is None or build.pdf_sha256 is None:
        return None
    # Хранилище могли очистить (например, в dev) — тогда собираем заново.
    if not await storage.exists(build.pdf_sha256):
        return None
    return build


async def _pack(storage: Storage, inputs: list[BuildInput]) -> bytes:
    files = [
        (item.path, item.text if item.text is not None else await storage.get(item.sha256))
        for item in inputs
    ]
    # Упаковка проекта до 200 МБ — работа процессора, не для потока API.
    return await asyncio.to_thread(pack_project, files)


async def _call_compiler[T](project_id: uuid.UUID, call: Awaitable[T]) -> T:
    """Ждёт ответ компилятора; если он недоступен или ответил не по контракту — 500."""
    try:
        return await call
    except CompilerUnavailableError as error:
        logger.warning("compiler_unavailable", project_id=str(project_id), reason=str(error))
        raise AppError(ErrorCode.INTERNAL, COMPILER_UNAVAILABLE_MESSAGE, 500) from error
    except CompilerRejectedError as error:
        # Бэкенд проверяет запрос заранее — значит, проверки разошлись с компилятором.
        logger.error(
            "compiler_rejected_build",
            project_id=str(project_id),
            status=error.status,
            code=error.code,
            locs=error.locs,
        )
        raise AppError(ErrorCode.INTERNAL, INTERNAL_MESSAGE, 500) from error
    except CompilerError as error:
        logger.error("compiler_bad_response", project_id=str(project_id), reason=str(error))
        raise AppError(ErrorCode.INTERNAL, INTERNAL_MESSAGE, 500) from error


async def _store_result(storage: Storage, result: CompileResult, sources: dict[str, str]) -> Build:
    """Кладёт файлы сборки в Storage, разбирает лог и возвращает строку builds
    без проекта и ключа."""
    status = result.status
    # Лог бывает десятки МБ — разбор не для потока API.
    parsed = await asyncio.to_thread(parse_log, result.log, sources)
    errors = list(parsed.errors)
    pdf_sha256 = None
    if result.pdf is not None and len(result.pdf) > MAX_PDF_BYTES:
        status = "error"
        errors.insert(
            0,
            _problem(
                f"PDF получился больше {MAX_PDF_BYTES // MB} МБ. "
                "Уменьшите картинки: сожмите их или сохраните в JPEG."
            ),
        )
    elif result.pdf is not None:
        pdf_sha256 = await storage.put(result.pdf)
    elif status == "ok":
        # Компилятор так не отвечает (9.7), но успешная сборка без PDF попала бы в кэш.
        status = "error"
    if status == "timeout":
        errors.insert(
            0,
            _problem(
                f"Сборка не уложилась в {BUILD_TIMEOUT_S} секунд. Возможно, в документе "
                "бесконечный цикл или слишком много больших картинок."
            ),
        )
    return Build(
        status=status,
        pdf_sha256=pdf_sha256,
        log_sha256=await storage.put(result.log),
        synctex_sha256=await storage.put(result.synctex) if result.synctex is not None else None,
        errors=[error.model_dump() for error in errors],
        # Страницы — только у PDF, который можно открыть. При ошибке TeX тоже пишет
        # «Output written … (N pages)», но PDF из этого не получился.
        pages=parsed.pages if pdf_sha256 is not None else None,
        duration_ms=result.duration_ms,
    )


async def _save(session: AsyncSession, build: Build, *, cached: bool) -> Build:
    session.add(build)
    await session.commit()
    logger.info(
        "build_finished",
        project_id=str(build.project_id),
        build_id=str(build.id),
        status=build.status,
        cached=cached,
        duration_ms=build.duration_ms,
    )
    return build
