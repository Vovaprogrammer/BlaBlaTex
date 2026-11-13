"""ProjectTools поверх сервисов (architecture.md 9.4): чем агент работает с настоящим проектом.

Каждый вызов открывает свою короткую сессию БД: прогон агента идёт минутами, а соединение
между вызовами свободно. Ошибки сервисов, которые модель может исправить, становятся
ToolError с тем же кодом, что в REST (9.2). Записи идут в changeset из ToolContext с автором
actor и шлют те же события file.*, что правки через сайт; без changeset в контексте
инструменты создают свой при первой записи и пишут дальше в него.

Что ведёт себя так же, как фейк для тестов агента, проверяют общие тесты
tests/project_tools_contract.py.
"""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.core.events import EventPublisher
from app.core.storage import BlobNotFoundError, Storage
from app.modules.builds import service as builds_service
from app.modules.builds import tasks as builds_tasks
from app.modules.builds.compiler import CompilerClient
from app.modules.builds.schemas import BuildError
from app.modules.checks import service as checks_service
from app.modules.checks.schemas import CheckResult
from app.modules.materials import service as materials_service
from app.modules.profiles import service as profiles_service
from app.modules.profiles.schemas import ProfileOut
from app.modules.projects import history
from app.modules.projects import service as projects_service
from app.modules.projects.history import Writer
from app.modules.projects.models import File, Project
from app.modules.projects.paths import InvalidPathError
from app.modules.projects.schemas import FileInfo
from app.modules.projects.tools import (
    DEFAULT_MATERIAL_LIMIT,
    DEFAULT_MAX_RESULTS,
    BuildResult,
    EditResult,
    FileText,
    ImageData,
    MaterialInfo,
    MaterialText,
    SearchHit,
    TemplateGuide,
    ToolContext,
    ToolError,
    ToolErrorCode,
    check_image,
    check_search,
    material_not_found,
    material_not_ready,
    material_slice,
    not_text_file,
    read_lines,
    replace_once,
    search_texts,
)
from app.modules.templates import service as templates_service
from app.modules.templates.registry import Registry

# Сколько compile ждёт итог. Больше одной сборки (60 с) с очередью за идущей сборкой
# проекта, но меньше срока, после которого сборку считают зависшей (3 минуты).
COMPILE_TIMEOUT_S = 120.0
COMPILE_TIMEOUT_MESSAGE = (
    "Сборка не закончилась за 2 минуты и продолжается. Вызовите compile ещё раз позже, "
    "чтобы узнать итог."
)


class ServiceProjectTools:
    """ProjectTools над проектом из ToolContext: файлы — через сервис файлов, сборка —
    через очередь сборок, материалы — из material_text, шаблон — из реестра шаблонов."""

    def __init__(
        self,
        context: ToolContext,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: Storage,
        events: EventPublisher,
        templates: Registry,
        enqueue: builds_tasks.Enqueue = builds_tasks.enqueue_build,
        poll_s: float = builds_service.WAIT_POLL_S,
        compiler: CompilerClient | None = None,
    ) -> None:
        self.context = context
        self._sessions = sessionmaker
        self._storage = storage
        self._events = events
        self._templates = templates
        self._enqueue = enqueue
        self._poll_s = poll_s
        # По версии компилятора run_checks находит сборку текущих файлов; без него ставит
        # новую, и воркер отдаёт успешную из кэша сам.
        self._compiler = compiler
        self._changeset_id = context.changeset_id
        # Модель может вызвать инструменты параллельно: первые записи создадут один changeset.
        self._changeset_lock = asyncio.Lock()

    async def list_files(self) -> list[FileInfo]:
        with _tool_errors():
            async with self._sessions() as session:
                await self._project(session)
                files = await projects_service.list_files(session, self.context.project_id)
        return [_info(file) for file in files]

    async def read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> FileText:
        with _tool_errors():
            async with self._sessions() as session:
                file = await projects_service.read_file(session, self.context.project_id, path)
        if file.content is None:
            raise not_text_file(file.path)
        return read_lines(file.path, file.version, file.content, start_line, end_line)

    async def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchHit]:
        check_search(query, max_results)
        with _tool_errors():
            async with self._sessions() as session:
                await self._project(session)
                texts = await projects_service.search_text_files(
                    session, self.context.project_id, query
                )
        return search_texts(texts, query, max_results)

    async def write_file(self, path: str, content: str) -> FileInfo:
        writer = await self._writer()
        with _tool_errors():
            async with self._sessions() as session:
                file, _ = await projects_service.write_text_file(
                    session, writer, self.context.project_id, path, content
                )
        return _info(file)

    async def edit_file(self, path: str, old: str, new: str) -> EditResult:
        line = 0

        def replace(text: str) -> str:
            nonlocal line
            replaced, line = replace_once(text, old, new)
            return replaced

        writer = await self._writer()
        with _tool_errors():
            async with self._sessions() as session:
                # Замена — под блокировкой проекта: между чтением и записью файл не изменится.
                file = await projects_service.edit_text_file(
                    session, writer, self.context.project_id, path, replace
                )
        return EditResult(file=_info(file), line=line)

    async def delete_file(self, path: str) -> None:
        writer = await self._writer()
        with _tool_errors():
            async with self._sessions() as session:
                await projects_service.delete_path(session, writer, self.context.project_id, path)

    async def compile(self) -> BuildResult:
        """Ставит сборку в очередь и ждёт итог не дольше COMPILE_TIMEOUT_S.

        Не дождался — status=timeout с сообщением, а сборка идёт дальше. Очередь недоступна —
        ToolError internal: об этом нужно сказать студенту.
        """
        with _tool_errors():
            async with self._sessions() as session:
                project = await self._project(session)
                build_id = (await builds_tasks.request_build(session, project, self._enqueue)).id
        try:
            # Срок — внутри ожидания, а не asyncio.timeout снаружи: тот мог бы оборвать
            # запрос к базе на середине и сломать соединение.
            build = await builds_service.wait_for_build(
                self._sessions, build_id, poll_s=self._poll_s, timeout_s=COMPILE_TIMEOUT_S
            )
        except TimeoutError:
            problem = BuildError(
                file=None, line=None, message=COMPILE_TIMEOUT_MESSAGE, context="", severity="error"
            )
            return BuildResult(
                status="timeout", build_id=build_id, pages=None, errors=[problem], warnings_count=0
            )
        if build is None:
            # Сборку удалили вместе с проектом.
            raise ToolError(ToolErrorCode.NOT_FOUND, projects_service.PROJECT_NOT_FOUND_MESSAGE)
        errors = [BuildError.model_validate(error) for error in build.errors]
        return BuildResult.model_validate(
            {
                "status": build.status,
                "build_id": build.id,
                "pages": build.pages,
                "errors": errors,
                "warnings_count": sum(error.severity == "warning" for error in errors),
            }
        )

    async def list_materials(self) -> list[MaterialInfo]:
        with _tool_errors():
            async with self._sessions() as session:
                await self._project(session)
                files = await projects_service.list_material_files(session, self.context.project_id)
                rows = await materials_service.statuses(session, [file.id for file in files])
        materials = []
        for file in files:
            row = rows.get(file.id)
            materials.append(
                MaterialInfo(
                    path=file.path,
                    mime=file.mime,
                    size=file.size,
                    # Строки ещё нет — текст точно не извлечён.
                    status=row.status if row is not None else "pending",
                    description=row.description if row is not None else None,
                )
            )
        return materials

    async def read_material(
        self, path: str, offset: int = 0, limit: int = DEFAULT_MATERIAL_LIMIT
    ) -> MaterialText:
        with _tool_errors():
            async with self._sessions() as session:
                file = await projects_service.find_file(session, self.context.project_id, path)
                if file is None or file.role != "material" or file.kind == "folder":
                    raise material_not_found()
                row = (await materials_service.statuses(session, [file.id])).get(file.id)
        if row is None or row.status != "ready":
            raise material_not_ready(
                row.status if row is not None else "pending", row.error if row else None
            )
        return material_slice(row.text or "", offset, limit)

    async def get_image(self, path: str) -> ImageData:
        with _tool_errors():
            async with self._sessions() as session:
                file = await projects_service.find_file(session, self.context.project_id, path)
        if file is None or file.kind == "folder":
            raise ToolError(ToolErrorCode.NOT_FOUND, projects_service.FILE_NOT_FOUND_MESSAGE)
        check_image(file.path)
        if file.blob_sha256 is None or file.mime is None:
            raise not_text_file(file.path)
        try:
            data = await self._storage.get(file.blob_sha256)
        except BlobNotFoundError:
            raise ToolError(
                ToolErrorCode.NOT_FOUND,
                f"Содержимое файла {file.path} потеряно: его нужно загрузить ещё раз",
            ) from None
        return ImageData(data=data, mime=file.mime)

    async def get_template_guide(self) -> TemplateGuide:
        async with self._sessions() as session:
            project = await self._project(session)
        template = self._templates.get(project.template_slug)
        if template is None:
            raise ToolError(ToolErrorCode.NOT_FOUND, templates_service.TEMPLATE_GONE_MESSAGE)
        return templates_service.template_guide(template.manifest, project.fields)

    async def get_profile(self) -> ProfileOut:
        async with self._sessions() as session:
            profile = await profiles_service.get_profile(session, self.context.user_id)
        return ProfileOut.model_validate(profile, from_attributes=True)

    async def run_checks(self) -> CheckResult:
        """Проверки, как POST /checks (9.1), но сборку ждёт до 2 минут, как compile, и в
        лимит сборок она не идёт: её ограничивает прогон."""
        with _tool_errors():
            return await checks_service.run_checks(
                self._sessions,
                self._storage,
                self._templates,
                self.context.project_id,
                compiler=self._compiler,
                enqueue=self._enqueue,
                wait_s=COMPILE_TIMEOUT_S,
                poll_s=self._poll_s,
            )

    async def _project(self, session: AsyncSession) -> Project:
        project = await projects_service.get_project(session, self.context.project_id)
        if project is None:
            raise ToolError(ToolErrorCode.NOT_FOUND, projects_service.PROJECT_NOT_FOUND_MESSAGE)
        return project

    async def _writer(self) -> Writer:
        """Кто пишет: actor из контекста, в changeset контекста или созданный при первой записи."""
        async with self._changeset_lock:
            if self._changeset_id is None:
                async with self._sessions() as session:
                    await self._project(session)
                    changeset = await history.create_changeset(
                        session,
                        self.context.project_id,
                        self.context.actor,
                        self.context.user_id,
                    )
                    await session.commit()
                self._changeset_id = changeset.id
            changeset_id: uuid.UUID = self._changeset_id
        return Writer(self._events, self.context.actor, self.context.user_id, changeset_id)


@contextmanager
def _tool_errors() -> Iterator[None]:
    """Ошибки сервисов, которые модель может исправить, — ToolError с тем же кодом (9.4).

    Остальные исключения (сбой базы, ошибка в коде) выходят как есть: прогон завершится
    со статусом failed.
    """
    try:
        yield
    except InvalidPathError as error:
        raise ToolError(ToolErrorCode.INVALID_PATH, str(error)) from None
    except AppError as error:
        try:
            code = ToolErrorCode(error.code.value)
        except ValueError:
            # У сервиса файлов таких ошибок для агента нет; если появятся — это сбой.
            code = ToolErrorCode.INTERNAL
        raise ToolError(code, error.message, error.details) from None


def _info(file: File) -> FileInfo:
    return FileInfo.model_validate(file, from_attributes=True)
