"""Настоящая ProjectTools поверх сервисов (architecture.md 9.4): общий контракт с фейком
и то, что есть только у неё — changeset, поиск в базе, материалы, картинки, сборка."""

import io
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq.exceptions import SendTaskError

from app.core.errors import AppError
from app.core.storage import LocalStorage
from app.modules.auth import service as auth_service
from app.modules.builds.models import Build
from app.modules.builds.service import run_project_builds
from app.modules.builds.tasks import Enqueue
from app.modules.materials.models import MaterialText
from app.modules.profiles.schemas import ProfileOut
from app.modules.projects import history, service_tools
from app.modules.projects import service as projects_service
from app.modules.projects.models import Changeset, File, FileRevision, Project
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service_tools import ServiceProjectTools
from app.modules.projects.tools import Actor, ProjectTools, ToolContext, ToolErrorCode
from app.modules.templates import service as templates_service
from app.modules.templates.registry import Registry, load_templates
from tests.fake_compiler import FakeCompiler
from tests.fake_events import FakeEvents
from tests.file_samples import PNG, SVG
from tests.helpers import TEMPLATE_FIXTURES, TEST_TEMPLATES, lab_project, writer
from tests.project_tools_contract import (
    FILES,
    GENERATED,
    MAIN,
    MakeTools,
    ProjectToolsContract,
    expect_error,
)

TEMPLATES: Registry = load_templates(TEMPLATE_FIXTURES)
BuildTools = Callable[..., ServiceProjectTools]


async def no_worker(build_id: uuid.UUID) -> None:
    """Очередь без воркера: сборка так и остаётся ждать."""


@pytest.fixture
def sessions(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Сессии инструментов: у каждого вызова своя, но все — внутри транзакции теста."""
    return async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def events() -> FakeEvents:
    return FakeEvents()


@pytest.fixture
def build_tools(
    sessions: async_sessionmaker[AsyncSession], storage: LocalStorage, events: FakeEvents
) -> BuildTools:
    def build(
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        actor: Actor = "ai",
        changeset_id: uuid.UUID | None = None,
        enqueue: Enqueue = no_worker,
    ) -> ServiceProjectTools:
        return ServiceProjectTools(
            ToolContext(project_id, user_id, actor, changeset_id),
            sessionmaker=sessions,
            storage=storage,
            events=events,
            templates=TEMPLATES,
            enqueue=enqueue,
            poll_s=0.01,
        )

    return build


async def new_user(session: AsyncSession) -> uuid.UUID:
    user, _ = await auth_service.register(
        session, f"student-{uuid.uuid4().hex[:8]}@example.com", "password1"
    )
    return user.id


async def new_project(
    session: AsyncSession, files: Mapping[str, str] = FILES
) -> tuple[uuid.UUID, uuid.UUID]:
    """Проект с файлами и meta.tex; возвращает id проекта и владельца."""
    owner = await new_user(session)
    project = await projects_service.create_project(
        session, owner, lab_project(), files, generated=GENERATED
    )
    return project.id, owner


class TestServiceProjectTools(ProjectToolsContract):
    @pytest.fixture
    def make_tools(self, db_session: AsyncSession, build_tools: BuildTools) -> MakeTools:
        async def make(
            files: Mapping[str, str],
            generated: Mapping[str, str] | None = None,
            actor: Actor = "ai",
        ) -> ProjectTools:
            owner = await new_user(db_session)
            project = await projects_service.create_project(
                db_session, owner, lab_project(), files, generated
            )
            return build_tools(project.id, owner, actor=actor)

        return make


async def revisions_in(session: AsyncSession, changeset_id: uuid.UUID) -> list[str | None]:
    """Прежние пути файлов, которые changeset изменил (None — файла не было)."""
    result = await session.scalars(
        select(FileRevision.path)
        .where(FileRevision.changeset_id == changeset_id)
        .order_by(FileRevision.id)
    )
    return list(result)


async def test_writes_go_to_changeset_of_run(
    db_session: AsyncSession, build_tools: BuildTools, events: FakeEvents
) -> None:
    pid, owner = await new_project(db_session)
    run = await history.create_changeset(db_session, pid, "ai", owner)
    tools = build_tools(pid, owner, changeset_id=run.id)

    await tools.write_file("sections/progress.tex", "Ход работы\n")
    await tools.edit_file("main.tex", "\\input{sections/goal}", "\\input{sections/progress}")
    await tools.delete_file("sections/goal.tex")

    # Новый файл (папка sections уже была), прежний main.tex и удалённый goal.tex.
    assert await revisions_in(db_session, run.id) == [None, "main.tex", "sections/goal.tex"]
    authors = {event.data.model_dump().get("author", "ai") for event in events.published}
    changesets = {event.data.model_dump()["changeset_id"] for event in events.published}
    assert (authors, changesets) == ({"ai"}, {run.id})


async def test_without_changeset_tools_create_one(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    pid, owner = await new_project(db_session)
    tools = build_tools(pid, owner)

    await tools.write_file("a.tex", "1")
    await tools.write_file("b.tex", "2")

    [changeset] = await db_session.scalars(
        select(Changeset).where(Changeset.project_id == pid, Changeset.author == "ai")
    )
    assert changeset.author_user_id == owner
    assert len(await revisions_in(db_session, changeset.id)) == 2


async def test_failed_call_does_not_break_next(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    pid, owner = await new_project(db_session)
    tools = build_tools(pid, owner)

    await expect_error(tools.write_file("meta.tex", "x"), ToolErrorCode.FORBIDDEN)
    await expect_error(tools.edit_file("main.tex", "нет такого", "x"), ToolErrorCode.EDIT_NOT_FOUND)

    # У каждого вызова своя сессия: после ошибки блокировка проекта не висит.
    assert (await tools.write_file("a.tex", "дальше")).path == "a.tex"


async def test_search_takes_percent_and_underscore_literally(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    pid, owner = await new_project(
        db_session,
        {"a.tex": "готово на 100%\n", "b.tex": "готово на 1000\n", "c.tex": "a_b\naxb\n"},
    )
    tools = build_tools(pid, owner)

    assert [hit.path for hit in await tools.search("0%")] == ["a.tex"]
    assert [(hit.path, hit.line) for hit in await tools.search("a_b")] == [("c.tex", 1)]
    # Обратная косая — тоже обычный символ, а не экранирование LIKE.
    assert {hit.path for hit in await tools.search("\\def\\bbt")} == {"meta.tex"}


async def test_materials_and_their_text(db_session: AsyncSession, build_tools: BuildTools) -> None:
    pid, owner = await new_project(
        db_session, {**FILES, "materials/lab.py": "print(1)\n", "materials/task.txt": "?"}
    )
    files = {
        file.path: file.id
        for file in await db_session.scalars(select(File).where(File.project_id == pid))
    }
    # Так строки material_text заполнит извлечение текста (B2.7).
    await db_session.execute(
        update(MaterialText)
        .where(MaterialText.file_id == files["materials/lab.py"])
        .values(status="ready", text="print(1)\n", description="Код программы")
    )
    await db_session.execute(
        update(MaterialText)
        .where(MaterialText.file_id == files["materials/task.txt"])
        .values(status="failed", error="Файл пустой")
    )
    tools = build_tools(pid, owner)

    materials = {item.path: item for item in await tools.list_materials()}
    part = await tools.read_material("materials/lab.py", offset=6, limit=1)
    failed = await expect_error(
        tools.read_material("materials/task.txt"), ToolErrorCode.MATERIAL_NOT_READY
    )

    assert set(materials) == {"materials/lab.py", "materials/task.txt"}
    lab = materials["materials/lab.py"]
    assert (lab.status, lab.description, lab.size, lab.mime) == (
        "ready",
        "Код программы",
        9,
        "text/plain",
    )
    assert (part.text, part.offset, part.total) == ("1", 6, 9)
    assert "Файл пустой" in failed.message
    await expect_error(tools.read_material("main.tex"), ToolErrorCode.NOT_FOUND)
    await expect_error(tools.read_material("materials"), ToolErrorCode.NOT_FOUND)


async def upload(
    session: AsyncSession, storage: LocalStorage, pid: uuid.UUID, path: str, data: bytes
) -> None:
    folder, _, name = path.rpartition("/")
    incoming = projects_service.IncomingFile(name, io.BytesIO(data), len(data))
    checked = await projects_service.check_uploads(folder, [incoming])
    await projects_service.save_uploads(session, storage, writer(), pid, checked)


async def test_get_image(
    db_session: AsyncSession, build_tools: BuildTools, storage: LocalStorage
) -> None:
    pid, owner = await new_project(db_session)
    await upload(db_session, storage, pid, "figures/plot.PNG", PNG)
    await upload(db_session, storage, pid, "figures/scheme.svg", SVG)
    tools = build_tools(pid, owner)

    image = await tools.get_image("figures/plot.PNG")

    assert (image.data, image.mime) == (PNG, "image/png")
    await expect_error(tools.get_image("figures/scheme.svg"), ToolErrorCode.UNSUPPORTED_FILE_TYPE)
    await expect_error(tools.get_image("main.tex"), ToolErrorCode.UNSUPPORTED_FILE_TYPE)
    await expect_error(tools.get_image("figures/none.png"), ToolErrorCode.NOT_FOUND)
    await expect_error(tools.get_image("figures"), ToolErrorCode.NOT_FOUND)
    await expect_error(tools.read_file("figures/plot.PNG"), ToolErrorCode.UNSUPPORTED_FILE_TYPE)


async def test_lost_picture_is_not_found(
    db_session: AsyncSession, build_tools: BuildTools, storage: LocalStorage
) -> None:
    pid, owner = await new_project(db_session)
    await upload(db_session, storage, pid, "plot.png", PNG)
    blob = await db_session.scalar(
        select(File.blob_sha256).where(File.project_id == pid, File.path == "plot.png")
    )
    assert blob is not None
    await storage.delete(blob)

    await expect_error(build_tools(pid, owner).get_image("plot.png"), ToolErrorCode.NOT_FOUND)


async def test_template_guide_and_profile(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    owner = await new_user(db_session)
    data = ProjectCreate(title="ЛР 1", template_slug="test-lab", fields=TEST_TEMPLATES["test-lab"])
    project = await templates_service.create_project(db_session, owner, data, TEMPLATES)
    tools = build_tools(project.id, owner)

    guide = await tools.get_template_guide()
    profile = await tools.get_profile()

    manifest = TEMPLATES["test-lab"].manifest
    assert (guide.slug, guide.main_file, guide.ai_rules) == (
        "test-lab",
        "main.tex",
        manifest.ai_rules,
    )
    assert [section.id for section in guide.sections] == [s.id for s in manifest.sections]
    fields = {field.key: (field.value, field.macro) for field in guide.fields}
    assert fields["lab_number"] == (1, "\\bbtLabNumber")
    assert any(macro.usage.startswith("\\bbtScreenshot") for macro in guide.macros)
    assert guide.discipline == manifest.discipline
    assert isinstance(profile, ProfileOut)
    assert profile.last_name == ""


async def test_guide_discipline_from_project_field(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    owner = await new_user(db_session)
    fields = TEST_TEMPLATES["test-any-lab"]
    data = ProjectCreate(title="ЛР 1", template_slug="test-any-lab", fields=fields)
    project = await templates_service.create_project(db_session, owner, data, TEMPLATES)

    guide = await build_tools(project.id, owner).get_template_guide()

    # То же, что в \bbtDiscipline, но текстом: без экранирования TeX.
    assert guide.discipline == "Тестирование & отладка"
    macros = {field.key: field.macro for field in guide.fields}
    assert macros["discipline"] == "\\bbtDiscipline"


@pytest.mark.parametrize(
    ("value", "discipline"),
    [("  Сети   связи ", "Сети связи"), ("   ", None), (None, None)],
)
def test_guide_discipline_is_one_line_like_title_page(
    value: str | None, discipline: str | None
) -> None:
    manifest = TEMPLATES["test-any-lab"].manifest
    values: dict[str, str | int] = {"lab_number": 1}
    if value is not None:
        values["discipline"] = value

    assert templates_service.template_guide(manifest, values).discipline == discipline


@pytest.mark.parametrize(
    ("value", "discipline"), [(" Сети\n  связи ", "Сети связи"), ("", None), ("  ", None)]
)
def test_guide_discipline_from_template_like_title_page(value: str, discipline: str | None) -> None:
    manifest = TEMPLATES["test-lab"].manifest.model_copy(update={"discipline": value})

    assert templates_service.template_guide(manifest, {}).discipline == discipline


async def test_guide_of_removed_template_is_not_found(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    pid, owner = await new_project(db_session)
    await db_session.execute(update(Project).where(Project.id == pid).values(template_slug="gone"))

    await expect_error(build_tools(pid, owner).get_template_guide(), ToolErrorCode.NOT_FOUND)


async def test_compile_waits_for_result(
    db_session: AsyncSession,
    build_tools: BuildTools,
    sessions: async_sessionmaker[AsyncSession],
    storage: LocalStorage,
) -> None:
    pid, owner = await new_project(db_session, {"main.tex": MAIN})
    compiler = FakeCompiler()

    async def worker(build_id: uuid.UUID) -> None:
        # Воркер собирает сразу, пока compile ждёт итог.
        await run_project_builds(sessions, storage, compiler.client(), FakeEvents(), build_id)

    result = await build_tools(pid, owner, enqueue=worker).compile()

    assert (result.status, result.errors, result.warnings_count) == ("ok", [], 0)
    assert len(compiler.requests) == 1


async def test_compile_gives_up_but_build_goes_on(
    db_session: AsyncSession, build_tools: BuildTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, owner = await new_project(db_session, {"main.tex": MAIN})
    monkeypatch.setattr(service_tools, "COMPILE_TIMEOUT_S", 0.05)

    result = await build_tools(pid, owner).compile()

    assert (result.status, result.pages) == ("timeout", None)
    assert "2 минуты" in result.errors[0].message
    # Сборка не отменена: она в очереди и соберётся, когда до неё дойдёт воркер.
    assert await db_session.scalar(select(Build.status).where(Build.id == result.build_id)) == (
        "queued"
    )


async def test_compile_when_queue_is_down(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    pid, owner = await new_project(db_session, {"main.tex": MAIN})

    async def broken(build_id: uuid.UUID) -> None:
        raise SendTaskError

    await expect_error(build_tools(pid, owner, enqueue=broken).compile(), ToolErrorCode.INTERNAL)


async def test_deleted_project_is_not_found(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    pid, owner = await new_project(db_session)
    tools = build_tools(pid, owner)
    project = await db_session.get_one(Project, pid)
    await projects_service.delete_project(db_session, project)

    # Вызовы создаются по одному: упавшая проверка не оставит неожиданных корутин.
    calls: list[Callable[[], Awaitable[object]]] = [
        tools.list_files,
        lambda: tools.search("цель"),
        lambda: tools.write_file("a.tex", "x"),
        lambda: tools.read_file("main.tex"),
        tools.list_materials,
        tools.compile,
    ]
    for call in calls:
        await expect_error(call(), ToolErrorCode.NOT_FOUND)


async def test_service_keeps_agent_out_of_materials(db_session: AsyncSession) -> None:
    pid, _ = await new_project(db_session, {**FILES, "materials/lab.py": "print(1)\n"})
    agent = writer(author="ai")

    # Запрет — в сервисе файлов: его не обойти и переносом, которого у инструментов нет.
    for from_, to in (("main.tex", "materials/main.tex"), ("materials/lab.py", "lab.py")):
        with pytest.raises(AppError) as caught:
            await projects_service.move_path(db_session, agent, pid, from_, to)
        assert (caught.value.status, caught.value.code) == (403, "forbidden")
    # Студенту можно.
    await projects_service.move_path(db_session, writer(), pid, "materials/lab.py", "lab.py")


async def test_changed_guide_does_not_leak_into_next_call(
    db_session: AsyncSession, build_tools: BuildTools
) -> None:
    owner = await new_user(db_session)
    data = ProjectCreate(title="ЛР 1", template_slug="test-lab", fields=TEST_TEMPLATES["test-lab"])
    project = await templates_service.create_project(db_session, owner, data, TEMPLATES)
    tools = build_tools(project.id, owner)

    guide = await tools.get_template_guide()
    guide.macros[0].usage = "испорчено"

    assert (await tools.get_template_guide()).macros[0].usage != "испорчено"
