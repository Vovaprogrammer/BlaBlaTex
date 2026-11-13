"""Проверки проекта поверх сервисов (architecture.md 9.1, 9.4): снимок из базы, сборка
текущих файлов и сами проверки (engine.py).

Соединение с базой берётся только на короткие запросы: снимок проекта — одна транзакция,
поиск и постановка сборки — свои, ожидание сборки опрашивает базу раз в poll_s. Проверки
идут в отдельном потоке: большой отчёт не останавливает остальные запросы.

В лог — только id и числа: ни текста отчёта, ни подписей, ни материалов.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.storage import BlobNotFoundError, Storage
from app.modules.builds import service as builds_service
from app.modules.builds import tasks as builds_tasks
from app.modules.builds.compiler import CompilerClient, CompilerError
from app.modules.builds.models import Build
from app.modules.builds.schemas import BuildError
from app.modules.checks.context import BuildOutcome, MaterialSource, SectionSpec, Snapshot
from app.modules.checks.engine import check_project
from app.modules.checks.schemas import PDF_CHECKS, CheckId, CheckResult
from app.modules.materials import service as materials_service
from app.modules.profiles import service as profiles_service
from app.modules.projects import service as projects_service
from app.modules.projects.models import File
from app.modules.projects.schemas import Engine
from app.modules.templates import service as templates_service
from app.modules.templates.registry import Registry

logger = structlog.get_logger(__name__)

# Ожидание сборки: получает ожидание и возвращает сборку или None, если ждать перестали
# (клиент ушёл, сервер останавливается).
type Guard = Callable[[Awaitable[Build | None]], Awaitable[Build | None]]


@dataclass(frozen=True)
class _Project:
    """Снимок проекта и то, что нужно для сборки текущих файлов."""

    snapshot: Snapshot
    checks: list[CheckId]
    build_files: list[File]
    engine: Engine
    main_file: str


async def run_checks(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    templates: Registry,
    project_id: uuid.UUID,
    *,
    compiler: CompilerClient | None,
    enqueue: builds_tasks.Enqueue,
    wait_s: float,
    poll_s: float = builds_service.WAIT_POLL_S,
    before_build: Callable[[], Awaitable[None]] | None = None,
    guard: Guard | None = None,
) -> CheckResult:
    """Проверки проекта: по исходнику — сразу, по PDF — по сборке текущих файлов.

    Сборки нет — ждётся та, что уже в очереди или идёт, а нет и её — ставится новая (перед
    этим вызывается before_build: лимит сборок). Ждём не дольше wait_s; guard оборачивает
    ожидание. Не дождались — pdf_checked=False.
    Проекта или его шаблона нет — AppError 404; очередь недоступна — AppError 500.
    """
    started = time.monotonic()
    project = await _snapshot(sessionmaker, templates, project_id)
    outcome: BuildOutcome | None = None
    build: Build | None = None
    if PDF_CHECKS & set(project.checks):
        waiter = _BuildWaiter(
            sessionmaker,
            project_id,
            enqueue,
            deadline=time.monotonic() + wait_s,
            poll_s=poll_s,
            before_build=before_build,
            guard=guard,
        )
        build, current = await waiter.current_build(compiler, project)
        if current:
            outcome = await _outcome(storage, build)
    findings = await asyncio.to_thread(check_project, project.snapshot, project.checks, outcome)
    errors = sum(finding.level == "error" for finding in findings)
    result = CheckResult(
        findings=findings,
        errors_count=errors,
        warnings_count=len(findings) - errors,
        build_id=build.id if build is not None else None,
        pdf_checked=build is None or outcome is not None,
    )
    logger.info(
        "checks_done",
        project_id=str(project_id),
        build_id=str(result.build_id) if result.build_id else None,
        errors=result.errors_count,
        warnings=result.warnings_count,
        pdf_checked=result.pdf_checked,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return result


async def _snapshot(
    sessionmaker: async_sessionmaker[AsyncSession], templates: Registry, project_id: uuid.UUID
) -> _Project:
    """Файлы, материалы, профиль и поля проекта — одной транзакцией: проект на один момент."""
    async with sessionmaker() as session:
        project = await projects_service.get_project(session, project_id)
        if project is None:
            raise AppError(ErrorCode.NOT_FOUND, projects_service.PROJECT_NOT_FOUND_MESSAGE, 404)
        template = templates.get(project.template_slug)
        if template is None:
            raise AppError(ErrorCode.NOT_FOUND, templates_service.TEMPLATE_GONE_MESSAGE, 404)
        rows = await projects_service.list_snapshot_files(session, project_id)
        materials = [file for file, _ in rows if file.role == "material"]
        texts = await materials_service.statuses(session, [file.id for file in materials])
        profile = await profiles_service.get_profile(session, project.owner_id)
        fields = dict(project.fields)
        engine, main_file = project.engine, project.main_file
        profile_values = [
            profile.last_name,
            profile.first_name,
            profile.middle_name,
            profile.group_name,
            profile.faculty,
            profile.department,
        ]
    manifest = template.manifest
    sources = []
    for file in materials:
        row = texts.get(file.id)
        status = row.status if row is not None else "pending"
        sources.append(
            MaterialSource(
                path=file.path,
                status=status,
                text=row.text if row is not None and status == "ready" else None,
                description=row.description if row is not None else None,
            )
        )
    snapshot = Snapshot(
        main_file=main_file,
        sections=tuple(
            SectionSpec(section.title, section.file, section.required)
            for section in manifest.sections
        ),
        texts={file.path: file.content for file, _ in rows if file.content is not None},
        files=frozenset(file.path for file, _ in rows),
        materials=tuple(sources),
        values=tuple(
            str(value) for value in (*fields.values(), *profile_values) if value is not None
        ),
        field_keys=frozenset(field.key for field in manifest.fields),
        engine=engine,
    )
    return _Project(
        snapshot=snapshot,
        checks=list(manifest.checks),
        build_files=[file for file, in_build in rows if in_build],
        engine=engine,
        main_file=main_file,
    )


class _BuildWaiter:
    """Находит сборку текущих файлов для проверок по PDF, ставит её и ждёт до deadline."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        enqueue: builds_tasks.Enqueue,
        *,
        deadline: float,
        poll_s: float,
        before_build: Callable[[], Awaitable[None]] | None,
        guard: Guard | None,
    ) -> None:
        self._sessions = sessionmaker
        self._project_id = project_id
        self._enqueue = enqueue
        self._deadline = deadline
        self._poll_s = poll_s
        self._before_build = before_build
        self._guard = guard

    async def current_build(
        self, compiler: CompilerClient | None, project: _Project
    ) -> tuple[Build, bool]:
        """Сборка и признак «законченная сборка текущих файлов»: только тогда по её итогу
        и логу проверяется PDF.

        Есть законченная с тем же ключом кэша (раздел 6) — она. Иначе ждём сборку, которая
        уже стоит в очереди или идёт, а если такой нет — ставим новую. Так повторный запрос
        не ставит вторую сборку, пока первая не закончилась. Идущая сборка могла начаться
        до последней правки: если её ключ оказался другим, после неё ставится новая.
        """
        key = await _files_key(compiler, project)
        async with self._sessions() as session:
            if key is not None:
                done = await builds_service.finished_build(session, self._project_id, key)
                if done is not None:
                    return done, True
            latest = await builds_service.latest_build(session, self._project_id)
        # Ждущая в очереди прочитает файлы, когда начнётся, — она соберёт текущие. Ключ
        # идущей сверяется после неё; ключа не узнать — нужна новая.
        reuse = latest is not None and (
            latest.status == "queued" or (latest.status == "running" and key is not None)
        )
        if latest is not None and reuse:
            build = latest
        else:
            build = await self._new_build()
        verify = build.status == "running"
        waited = await self._wait(build)
        if waited is None or waited.status not in builds_service.FINISHED_STATUSES:
            return waited or build, False
        if not verify or waited.inputs_hash == key:
            return waited, True
        build = await self._new_build()
        waited = await self._wait(build)
        finished = waited is not None and waited.status in builds_service.FINISHED_STATUSES
        return waited or build, finished

    async def _new_build(self) -> Build:
        """Новая сборка, как POST /builds; перед ней — лимит сборок (before_build)."""
        if self._before_build is not None:
            await self._before_build()
        async with self._sessions() as session:
            project = await projects_service.get_project(session, self._project_id)
            if project is None:
                raise AppError(ErrorCode.NOT_FOUND, projects_service.PROJECT_NOT_FOUND_MESSAGE, 404)
            return await builds_tasks.request_build(session, project, self._enqueue)

    async def _wait(self, build: Build) -> Build | None:
        """Сборка, как только закончится, но не позже deadline — тогда как есть. None —
        ждать перестали (клиент ушёл, сервер останавливается) или проекта больше нет."""
        remaining = self._deadline - time.monotonic()
        if build.status in builds_service.FINISHED_STATUSES or remaining <= 0:
            return build
        waiting = builds_service.build_after_wait(
            self._sessions, build.id, timeout_s=remaining, poll_s=self._poll_s
        )
        return await (self._guard(waiting) if self._guard is not None else waiting)


async def _files_key(compiler: CompilerClient | None, project: _Project) -> str | None:
    """Ключ кэша текущих файлов, как его посчитает воркер (раздел 6), или None.

    Версию компилятора спрашиваем у него самого, как воркер; не ответил — ключа нет.
    """
    if compiler is None:
        return None
    try:
        version = await compiler.version()
    except CompilerError:
        return None
    return await asyncio.to_thread(
        builds_service.files_key,
        project.build_files,
        engine=project.engine,
        main=project.main_file,
        version=version,
    )


async def _outcome(storage: Storage, build: Build) -> BuildOutcome:
    """Итог законченной сборки для проверок: статус, число ошибок и лог."""
    errors = sum(BuildError.model_validate(error).severity == "error" for error in build.errors)
    log = None
    if build.log_sha256 is not None:
        try:
            log = await storage.get(build.log_sha256)
        except BlobNotFoundError:
            # Хранилище очистили (например, в dev): проверки по логу просто не найдут ничего.
            log = None
    return BuildOutcome(status=_FINISHED[build.status], errors=errors, log=log)


# Итог законченной сборки: queued и running сюда не попадают.
_FINISHED: dict[str, Literal["ok", "error", "timeout"]] = {
    "ok": "ok",
    "error": "error",
    "timeout": "timeout",
}
