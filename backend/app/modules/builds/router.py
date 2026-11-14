"""Сборки проекта и их артефакты (architecture.md 9.1). Логика — в service.py."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.core.db import DbSession, DbSessionmaker
from app.core.errors import TEXT_CONTENT, AppError, ErrorCode, not_implemented
from app.core.http import content_disposition, unless_client_left
from app.core.ratelimit import Limit, get_rate_limiter
from app.core.shutdown import ShutdownDep
from app.core.storage import BlobNotFoundError, StorageDep
from app.modules.builds import service, tasks
from app.modules.builds.dependencies import BUILD_NOT_FOUND_MESSAGE, BuildEnqueue, OwnedBuild
from app.modules.builds.models import Build
from app.modules.builds.schemas import BuildError, BuildOut, SyncTexEditOut, SyncTexViewOut
from app.modules.projects.dependencies import OwnedProject
from app.modules.projects.schemas import FilePath

router = APIRouter(tags=["builds"])

# Лог и PDF содержат текст пользователя: браузер не должен угадывать по нему тип
# и открывать, например, лог как HTML.
_NO_SNIFF = {"X-Content-Type-Options": "nosniff"}
# Запросов сборки на студента — с сайта и по токену вместе (9.1). Сборки агента внутри
# прогона идут не через этот маршрут и в лимит не входят: их ограничивает прогон.
BUILDS_LIMIT = Limit(count=60, period_s=10 * 60)
# Сколько GET /builds/{bid}?wait держит запрос. Обычная сборка укладывается в это время,
# а ответ не дольше минуты не оборвут ни прокси, ни HTTP-клиенты с обычными настройками.
BUILD_WAIT_MAX_S = 60
# Предел размера страницы PDF — 200 дюймов, в пунктах (1/72 дюйма).
MAX_PDF_COORDINATE = 14_400
# В текстовом файле до 2 МБ строк заведомо меньше.
MAX_SYNCTEX_LINE = 10_000_000


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
async def start_build(
    project: OwnedProject, session: DbSession, enqueue: BuildEnqueue, request: Request
) -> BuildOut:
    """Ставит сборку в очередь и сразу отвечает; собирает воркер (architecture.md 9.1).

    Пока сборка проекта ждёт в очереди, повторный запрос возвращает её же. Итог —
    статус сборки: ошибки LaTeX и недоступный компилятор — это status=error и список
    errors, а не HTTP-ошибка. Очередь недоступна — 500, сборка не создаётся.
    Больше 60 запросов за 10 минут — 429.
    """
    # Проект свой (OwnedProject), поэтому владелец — тот, кто просит сборку.
    await get_rate_limiter(request).check("builds", str(project.owner_id), BUILDS_LIMIT)
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
async def get_build(
    request: Request,
    build: OwnedBuild,
    session: DbSession,
    sessionmaker: DbSessionmaker,
    shutdown: ShutdownDep,
    wait: Annotated[
        int,
        Query(
            ge=0,
            le=BUILD_WAIT_MAX_S,
            description="Сколько секунд ждать итог, если сборка ещё в очереди или идёт: "
            f"0–{BUILD_WAIT_MAX_S}",
        ),
    ] = 0,
) -> BuildOut:
    """Сборка и её итог.

    С wait ответ приходит, как только сборка закончилась, но не позже чем через wait
    секунд; не дождались — сборка как есть (queued или running), запрос повторяют. Так
    агенту по токену на сборку хватает одного-двух запросов, а не запроса в секунду.
    """
    if wait == 0 or build.status in service.FINISHED_STATUSES:
        return _build_out(build)
    # Пока ждём, соединение запроса не нужно: возвращаем его в пул, а проверки идут
    # своими короткими сессиями. Иначе каждый ждущий клиент держал бы соединение минуту.
    await session.close()
    waited = await shutdown.unless_stopped(
        unless_client_left(
            request, service.build_after_wait(sessionmaker, build.id, timeout_s=wait)
        )
    )
    if shutdown.is_set() or await request.is_disconnected():
        # Сервер останавливается — ответ как было, клиент повторит запрос новому процессу.
        # Клиент ушёл — ответ никто не прочтёт.
        return _build_out(waited or build)
    if waited is None:
        raise AppError(ErrorCode.NOT_FOUND, BUILD_NOT_FOUND_MESSAGE, 404)
    return _build_out(waited)


@router.get(
    "/builds/{bid}/pdf",
    response_class=Response,
    responses={
        200: {
            "description": "PDF сборки",
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Content-Disposition": {
                    "description": "inline и имя отчёта на момент сборки, например "
                    "ЛР3_Чистяков.pdf; русское имя — в filename* (UTF-8)",
                    "schema": {"type": "string"},
                }
            },
        }
    },
)
async def build_pdf(build: OwnedBuild, session: DbSession, storage: StorageDep) -> Response:
    """PDF сборки; у сборки с ошибкой его нет — 404.

    inline — чтобы PDF открывался во вкладке, а ссылка с атрибутом download сохранит его
    под именем из заголовка: «ЛР3_Чистяков.pdf» на момент сборки (architecture.md 9.1).
    """
    name = build.pdf_name
    if name is None and build.pdf_sha256 is not None:
        # Сборка до B3.2 — имени у неё нет, считаем по данным сейчас.
        name = await service.legacy_pdf_name(session, build)
        if name is None:
            raise AppError(ErrorCode.NOT_FOUND, BUILD_NOT_FOUND_MESSAGE, 404)
    return await _artifact(
        storage,
        build.pdf_sha256,
        missing="У этой сборки нет PDF",
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(f"{name}.pdf")},
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


@router.get("/builds/{bid}/synctex/edit")
async def synctex_edit(
    build: OwnedBuild,
    page: Annotated[int, Query(ge=1, description="Страница PDF, от 1")],
    x: Annotated[
        float,
        Query(
            ge=0,
            le=MAX_PDF_COORDINATE,
            description="От левого края страницы, в пунктах PDF (1/72 дюйма)",
        ),
    ],
    y: Annotated[
        float,
        Query(
            ge=0,
            le=MAX_PDF_COORDINATE,
            description="От верхнего края страницы вниз, в пунктах PDF (1/72 дюйма)",
        ),
    ],
) -> SyncTexEditOut:
    """Что написано в этом месте страницы PDF: файл проекта и строка (Ctrl+клик в PDF).

    Здесь нет текста студента — титульный лист, номер страницы, пустое место — source: null,
    это не ошибка. Строки — как в файлах на момент сборки. У сборки нет SyncTeX — 404;
    больше 120 запросов SyncTeX в минуту — 429.
    """
    raise not_implemented()


@router.get("/builds/{bid}/synctex/view")
async def synctex_view(
    build: OwnedBuild,
    path: Annotated[
        FilePath, Query(description="Путь файла в проекте, например sections/goal.tex")
    ],
    line: Annotated[int, Query(ge=1, le=MAX_SYNCTEX_LINE, description="Номер строки, от 1")],
) -> SyncTexViewOut:
    """Где в PDF строка файла: прямоугольники на страницах (позиция курсора в PDF).

    Первый прямоугольник — самый точный. Строки нет в PDF — boxes пустой, это не ошибка;
    комментарий и пустая строка дают ближайший текст. Строки — как в файлах на момент сборки.
    У сборки нет SyncTeX — 404; больше 120 запросов SyncTeX в минуту — 429.
    """
    raise not_implemented()
