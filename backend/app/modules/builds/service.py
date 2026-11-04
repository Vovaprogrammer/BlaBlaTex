"""Сборки: файлы проекта → архив → компилятор → артефакты в Storage и строка в builds.

Сборка проходит статусы queued → running → ok | error | timeout. queue_build ставит её
в очередь, воркер собирает (run_project_builds, задача — builds/tasks.py). У проекта не
больше одной сборки в очереди и одной идущей — это держат уникальные индексы
(models.py), так что сборки одного проекта не идут параллельно, сколько бы ни было
воркеров. Файлы проекта модуль читает только через сервис projects.

Вкладки узнают о сборке из событий (9.3): build.started — когда сборка началась
(running), а не когда её поставили в очередь, build.finished — когда записан итог.
Оба шлёт тот, кто ведёт сборку, одно за другим, поэтому «началась» всегда приходит
раньше «готова». Сборку в очереди вкладка, нажавшая «Собрать», видит в ответе POST.
"""

import asyncio
import hashlib
import io
import json
import re
import tarfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

import structlog
from sqlalchemy import ColumnElement, Select, and_, delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.errors import INTERNAL_MESSAGE, AppError, ErrorCode
from app.core.events import BuildFinishedData, BuildStartedData, EventPublisher, EventType
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
from app.modules.builds.models import ONE_RUNNING_INDEX, Build
from app.modules.builds.schemas import BuildError, BuildStatus
from app.modules.projects import service as projects_service
from app.modules.projects.models import File, Project
from app.modules.projects.paths import OUT_DIR, is_in_out_dir
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

FINISHED_STATUSES: frozenset[BuildStatus] = frozenset(("ok", "error", "timeout"))
# Сборка идёт дольше — значит, её воркер упал. Считается от started_at: от начала сборки,
# а когда воркер получил место у компилятора — от отправки ему. Ожидание в очереди и места
# у компилятора не в счёт: под нагрузкой оно законно. Живой воркер укладывается в сборку
# (60 с), передачу файлов (до 30 с) и очередь компилятора: при одном процессе воркера её
# нет, при двух — до минуты.
STALE_AFTER = timedelta(minutes=3)
STALE_MESSAGE = "Сборка зависла и остановлена. Запустите её ещё раз."
# Сборка ждёт дольше, хотя у проекта ничего не идёт, — значит, её задание потерялось:
# например, упал воркер, который вёл предыдущую сборку проекта и передал бы очередь ей.
LOST_AFTER = timedelta(minutes=1)
# Как часто wait_for_build смотрит статус сборки.
WAIT_POLL_S = 1.0

COMPILER_UNAVAILABLE_MESSAGE = "Сервис сборки сейчас недоступен. Попробуйте через минуту."
# Внешний ключ builds → projects (имя по соглашению из core/db.py).
_PROJECT_FK = "fk_builds_project_id_projects"
# Поля итога: их записывает в строку сборки _finish.
_RESULT_FIELDS = (
    "status",
    "engine",
    "inputs_hash",
    "pdf_sha256",
    "log_sha256",
    "synctex_sha256",
    "errors",
    "pages",
    "duration_ms",
)


@dataclass(frozen=True)
class BuildInput:
    """Файл, который уходит в сборку. Текст уже в памяти, бинарный читается из Storage."""

    path: str
    sha256: str
    text: bytes | None


async def queue_build(session: AsyncSession, project: Project) -> tuple[Build, bool]:
    """Ставит сборку проекта в очередь и возвращает её и признак «новая». Коммитит сессию.

    Если сборка проекта уже ждёт в очереди, новая не создаётся — возвращается та: файлы
    она прочитает, когда начнётся, поэтому соберёт и последние правки. Идущая сборка не
    мешает: новая начнётся после неё. Проект удалили — 404.
    """
    _check_clean(session, "queue_build")
    # Ожидающую сборку могут начать между вставкой и чтением — тогда ставим новую.
    for _ in range(3):
        try:
            build = await session.scalar(
                insert(Build)
                .values(project_id=project.id, status="queued", engine=project.engine, errors=[])
                .on_conflict_do_nothing(
                    index_elements=[Build.project_id], index_where=Build.status == "queued"
                )
                .returning(Build)
            )
        except IntegrityError as error:
            await _raise_if_project_gone(session, error)
            raise
        created = build is not None
        if build is None:
            build = await session.scalar(_queued_build(project.id))
        if build is not None:
            await session.commit()
            return build, created
    raise RuntimeError("Не удалось поставить сборку в очередь: её всё время начинают")


async def start_build(
    session: AsyncSession, events: EventPublisher, build_id: uuid.UUID
) -> Build | None:
    """Начинает сборку из очереди: queued → running. Коммитит сессию и шлёт build.started.

    None — сборку уже начали (задание пришло повторно) или у проекта идёт другая сборка:
    эту возьмёт тот, кто ведёт ту (run_project_builds).
    """
    _check_clean(session, "start_build")
    build: Build | None = None
    try:
        # Точка сохранения: при отказе откатывается только она, а не вся транзакция —
        # полный откат сбросил бы объекты сессии, и в async их уже не прочитать.
        async with session.begin_nested():
            build = await session.scalar(
                update(Build)
                .where(Build.id == build_id, Build.status == "queued")
                .values(status="running", started_at=func.now())
                .returning(Build)
            )
    except IntegrityError as error:
        if ONE_RUNNING_INDEX not in str(error.orig):
            raise
    await session.commit()
    if build is not None:
        await events.publish(
            build.project_id, EventType.BUILD_STARTED, BuildStartedData(build_id=build.id)
        )
    return build


async def discard_queued_build(session: AsyncSession, build_id: uuid.UUID) -> None:
    """Удаляет сборку, которая ещё ждёт в очереди: например, её не удалось отправить воркеру."""
    await session.execute(delete(Build).where(Build.id == build_id, Build.status == "queued"))
    await session.commit()


async def run_queued_build(
    session: AsyncSession,
    storage: Storage,
    compiler: CompilerClient,
    events: EventPublisher,
    build_id: uuid.UUID,
) -> Build | None:
    """Начинает сборку из очереди, собирает и записывает итог.

    Ошибки LaTeX, таймаут, проблемы проекта и недоступный компилятор — это итог сборки
    (status=error или timeout и сообщение в errors), а не исключение. None — сборку не
    начали (см. start_build) или её итог уже не нужен: сборку посчитали зависшей или
    удалили вместе с проектом. Сессия коммитится по ходу: на время сборки соединение
    возвращается в пул.
    """
    build = await start_build(session, events, build_id)
    if build is None:
        return None
    return await _run_started(session, storage, compiler, events, build)


async def run_project_builds(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    compiler: CompilerClient,
    events: EventPublisher,
    build_id: uuid.UUID,
) -> None:
    """Собирает сборку из очереди, а за ней — ожидающие сборки того же проекта.

    Так сборки проекта идут по одной без блокировок: начать вторую не даст база
    (start_build вернёт None), а следующую из очереди берёт тот, кто закончил предыдущую.
    """
    next_id: uuid.UUID | None = build_id
    while next_id is not None:
        async with sessionmaker() as session:
            build = await start_build(session, events, next_id)
            if build is None:
                return
            project_id = build.project_id
            await _run_started(session, storage, compiler, events, build)
            next_id = await session.scalar(select(Build.id).where(_is_queued(project_id)))


async def mark_stale_builds(session: AsyncSession, events: EventPublisher) -> list[Build]:
    """Ставит timeout сборкам, которые идут дольше STALE_AFTER, и возвращает их.

    Их воркер, скорее всего, упал. Если он всё же жив, его итог уже не запишется
    (_finish пишет только в идущую сборку). Коммитит сессию; по каждой сборке вкладкам
    уходит build.finished.
    """
    stale = [_problem(STALE_MESSAGE).model_dump()]
    builds = list(
        await session.scalars(
            update(Build)
            .where(Build.status == "running", Build.started_at < func.now() - STALE_AFTER)
            .values(status="timeout", errors=stale)
            .returning(Build)
        )
    )
    await session.commit()
    for build in builds:
        logger.warning("build_stale", build_id=str(build.id), project_id=str(build.project_id))
        await _publish_finished(events, build)
    return builds


async def lost_queued_builds(session: AsyncSession) -> list[uuid.UUID]:
    """Сборки, которые ждут дольше LOST_AFTER, хотя у их проекта ничего не идёт.

    Их задание потерялось — их снова отправляют в очередь. Если задание всё же цело,
    вторая попытка ничего не сделает: начать сборку можно только один раз (start_build).
    """
    running = aliased(Build)
    result = await session.scalars(
        select(Build.id)
        .where(
            Build.status == "queued",
            Build.created_at < func.now() - LOST_AFTER,
            ~exists().where(running.project_id == Build.project_id, running.status == "running"),
        )
        .order_by(Build.created_at)
    )
    return list(result)


async def wait_for_build(
    sessionmaker: async_sessionmaker[AsyncSession],
    build_id: uuid.UUID,
    *,
    poll_s: float = WAIT_POLL_S,
    timeout_s: float | None = None,
) -> Build | None:
    """Ждёт итог сборки — для compile() у ИИ-агента (B2.5).

    Статус смотрится в базе раз в poll_s секунд: соединение между проверками свободно,
    а событий (B2.4) функция не ждёт. None — сборки больше нет: проект удалили.

    timeout_s — сколько ждать; не дождались — TimeoutError. Срок проверяется между
    проверками, а не посреди запроса к базе: asyncio.timeout снаружи мог бы оборвать
    запрос на середине, и соединение пришлось бы выбросить.
    """
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    while True:
        async with sessionmaker() as session:
            build = await session.get(Build, build_id)
        if build is None or build.status in FINISHED_STATUSES:
            return build
        if deadline is None:
            await asyncio.sleep(poll_s)
            continue
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError
        # Последняя проверка — ровно к сроку: сборка, закончившаяся в последний момент,
        # не потеряется.
        await asyncio.sleep(min(poll_s, left))


async def get_owned_build(
    session: AsyncSession, build_id: uuid.UUID, owner_id: uuid.UUID
) -> Build | None:
    """Сборка проекта владельца или None: чужая и несуществующая сборка не различаются."""
    build = await session.get(Build, build_id)
    if build is None:
        return None
    project = await projects_service.get_owned_project(session, build.project_id, owner_id)
    return build if project is not None else None


async def latest_build(session: AsyncSession, project_id: uuid.UUID) -> Build | None:
    """Последняя поставленная сборка проекта, в том числе ещё не законченная, или None,
    если сборок ещё не было."""
    return await session.scalar(
        select(Build)
        .where(Build.project_id == project_id)
        .order_by(Build.created_at.desc(), Build.id)
        .limit(1)
    )


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
    if any(is_in_out_dir(file.path) for file in files):
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


def _check_clean(session: AsyncSession, name: str) -> None:
    if session.new or session.dirty or session.deleted:
        raise RuntimeError(f"{name} коммитит сессию: сначала запишите или отмените изменения")


def _is_queued(project_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(Build.project_id == project_id, Build.status == "queued")


def _queued_build(project_id: uuid.UUID) -> Select[tuple[Build]]:
    return select(Build).where(_is_queued(project_id))


async def _run_started(
    session: AsyncSession,
    storage: Storage,
    compiler: CompilerClient,
    events: EventPublisher,
    build: Build,
) -> Build | None:
    """Собирает начатую сборку и записывает итог; None — итог уже не нужен."""
    # Значения — заранее: после отката ниже объекты сессии сброшены.
    build_id, project_id = build.id, build.project_id
    project = await projects_service.get_project(session, project_id)
    if project is None:
        # Проект удалили, а с ним и сборку.
        return None
    engine = project.engine

    async def restart_clock() -> None:
        # Ожидание места у компилятора не в счёт зависания (STALE_AFTER).
        await session.execute(
            update(Build)
            .where(Build.id == build_id, Build.status == "running")
            .values(started_at=func.now())
        )
        await session.commit()

    try:
        result, cached = await _produce(
            session, storage, compiler, project, on_compile=restart_clock
        )
    except CompilerError as error:
        result, cached = _failure(engine, _compiler_failure_message(project_id, error)), False
    except Exception:
        # Ошибка в коде или сбой базы: сборка не должна висеть «идущей» до проверки зависших.
        logger.exception("build_crashed", build_id=str(build_id), project_id=str(project_id))
        # Транзакция могла оборваться посреди запроса — без отката итог не записать.
        await session.rollback()
        result, cached = _failure(engine, INTERNAL_MESSAGE), False
    return await _finish(session, events, build_id, result, cached=cached)


async def _produce(
    session: AsyncSession,
    storage: Storage,
    compiler: CompilerClient,
    project: Project,
    *,
    on_compile: Callable[[], Awaitable[None]] | None = None,
) -> tuple[Build, bool]:
    """Собирает проект и возвращает итог — поля строки builds из _RESULT_FIELDS — и признак
    «из кэша». Сбой компилятора — CompilerError: что с ним делать, решает вызывающий.
    on_compile вызывается, когда запрос уходит компилятору (см. CompilerClient.compile)."""
    files = await projects_service.list_build_files(session, project.id)
    await _release_connection(session)

    problem = find_input_problem(files, project.main_file)
    if problem is not None:
        return Build(status="error", engine=project.engine, errors=[problem.model_dump()]), False

    # sha256 всех текстов проекта — работа процессора, не для цикла событий.
    inputs = await asyncio.to_thread(lambda: [_build_input(file) for file in files])
    version = await compiler.version()
    key = inputs_hash(inputs, engine=project.engine, main=project.main_file, version=version)

    cached = await _find_cached(session, storage, project.id, key)
    if cached is not None:
        # Файлы в Storage не копируются — они лежат по sha256.
        build = Build(
            status="ok",
            engine=project.engine,
            inputs_hash=key,
            pdf_sha256=cached.pdf_sha256,
            log_sha256=cached.log_sha256,
            synctex_sha256=cached.synctex_sha256,
            errors=list(cached.errors),
            pages=cached.pages,
            duration_ms=cached.duration_ms,
        )
        return build, True
    await _release_connection(session)

    archive = await _pack(storage, inputs)
    result = await compiler.compile(
        archive, main=project.main_file, engine=project.engine, on_start=on_compile
    )
    # Исходники — для файлов из лога и контекста вокруг ошибок.
    sources = {file.path: file.content for file in files if file.content is not None}
    build = await _store_result(storage, result, sources, project.engine)
    build.engine = project.engine
    build.inputs_hash = key
    return build, False


def _failure(engine: Engine, message: str) -> Build:
    """Итог сборки, которую не удалось провести, с сообщением для пользователя."""
    return Build(status="error", engine=engine, errors=[_problem(message).model_dump()])


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
    """Последняя успешная сборка проекта с тем же ключом, если все её файлы ещё в Storage."""
    build = await session.scalar(
        select(Build)
        .where(Build.project_id == project_id, Build.inputs_hash == key, Build.status == "ok")
        .order_by(Build.created_at.desc())
        .limit(1)
    )
    if build is None or build.pdf_sha256 is None:
        return None
    # Хранилище могли очистить (например, в dev) — тогда собираем заново.
    artifacts = (build.pdf_sha256, build.log_sha256, build.synctex_sha256)
    for sha256 in artifacts:
        if sha256 is not None and not await storage.exists(sha256):
            return None
    return build


async def _pack(storage: Storage, inputs: list[BuildInput]) -> bytes:
    files = [
        (item.path, item.text if item.text is not None else await storage.get(item.sha256))
        for item in inputs
    ]
    # Упаковка проекта до 200 МБ — работа процессора, не для потока API.
    return await asyncio.to_thread(pack_project, files)


def _compiler_failure_message(project_id: uuid.UUID, error: CompilerError) -> str:
    """Пишет сбой компилятора в лог и возвращает сообщение для пользователя."""
    if isinstance(error, CompilerUnavailableError):
        logger.warning("compiler_unavailable", project_id=str(project_id), reason=str(error))
        return COMPILER_UNAVAILABLE_MESSAGE
    if isinstance(error, CompilerRejectedError):
        # Бэкенд проверяет запрос заранее — значит, проверки разошлись с компилятором.
        logger.error(
            "compiler_rejected_build",
            project_id=str(project_id),
            status=error.status,
            code=error.code,
            locs=error.locs,
        )
    else:
        logger.error("compiler_bad_response", project_id=str(project_id), reason=str(error))
    return INTERNAL_MESSAGE


async def _store_result(
    storage: Storage, result: CompileResult, sources: dict[str, str], engine: Engine
) -> Build:
    """Кладёт файлы сборки в Storage, разбирает лог и возвращает строку builds
    без проекта и ключа."""
    status = result.status
    # Лог бывает десятки МБ — разбор не для потока API.
    parsed = await asyncio.to_thread(parse_log, result.log, sources, engine)
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


async def _finish(
    session: AsyncSession,
    events: EventPublisher,
    build_id: uuid.UUID,
    result: Build,
    *,
    cached: bool,
) -> Build | None:
    """Записывает итог в идущую сборку и шлёт build.finished. None — сборка уже не идёт:
    её посчитали зависшей (mark_stale_builds) или удалили вместе с проектом. Тогда итог
    не нужен и события нет: о зависшей сборке сообщила проверка."""
    build = await session.scalar(
        update(Build)
        .where(Build.id == build_id, Build.status == "running")
        .values({field: getattr(result, field) for field in _RESULT_FIELDS})
        .returning(Build)
    )
    await session.commit()
    if build is None:
        logger.warning("build_result_dropped", build_id=str(build_id), status=result.status)
        return None
    _log_finished(build, cached=cached)
    await _publish_finished(events, build)
    return build


async def _publish_finished(events: EventPublisher, build: Build) -> None:
    """build.finished по записанному итогу; errors_count — ошибки без предупреждений."""
    data = BuildFinishedData(
        build_id=build.id,
        status=build.status,
        pages=build.pages,
        errors_count=sum(error["severity"] == "error" for error in build.errors),
    )
    await events.publish(build.project_id, EventType.BUILD_FINISHED, data)


async def _raise_if_project_gone(session: AsyncSession, error: IntegrityError) -> None:
    """Сборка идёт минутами, и проект за это время могли удалить: тогда — 404."""
    if _PROJECT_FK in str(error.orig):
        await session.rollback()
        raise AppError(
            ErrorCode.NOT_FOUND, projects_service.PROJECT_NOT_FOUND_MESSAGE, 404
        ) from None


def _log_finished(build: Build, *, cached: bool) -> None:
    logger.info(
        "build_finished",
        project_id=str(build.project_id),
        build_id=str(build.id),
        status=build.status,
        cached=cached,
        duration_ms=build.duration_ms,
    )
