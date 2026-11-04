"""Задача извлечения текста материалов (architecture.md 5): когда ставится, что записывает,
повторы и гонки с правками файла — на настоящем Postgres."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq.exceptions import SendTaskError

from app.core.config import Settings
from app.core.events import EventType, MaterialReadyData
from app.core.storage import LocalStorage
from app.modules.materials import tasks
from app.modules.materials.extraction import SVG_MESSAGE, Extracted
from app.modules.materials.models import MaterialText
from app.modules.materials.tasks import FAILED_MESSAGE, extract_material
from app.modules.projects.dependencies import get_extract_materials
from app.modules.projects.models import Changeset, File
from tests.fake_events import FakeEvents
from tests.file_samples import SVG
from tests.helpers import backdate_changesets, create_empty_project
from tests.material_samples import make_docx, make_pdf

# Any — проект как JSON.
Project = dict[str, Any]
Extract = Callable[[str | None, str | bytes], Awaitable[Extracted]]


@pytest.fixture
async def project(user_client: AsyncClient, db_session: AsyncSession) -> Project:
    me = (await user_client.get("/api/v1/auth/me")).json()
    created = await create_empty_project(db_session, uuid.UUID(me["user"]["id"]))
    return {"id": str(created.id)}


@pytest.fixture
def sessions(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Сессии задачи: у каждого шага своя, но все — внутри транзакции теста."""
    return async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
def storage(settings: Settings) -> LocalStorage:
    """То же хранилище, куда пишет загрузка в API."""
    return LocalStorage(settings.storage_dir)


@pytest.fixture
def run_job(
    sessions: async_sessionmaker[AsyncSession], storage: LocalStorage, events: FakeEvents
) -> Callable[..., Awaitable[None]]:
    async def run(file_id: uuid.UUID, extract: Extract | None = None) -> None:
        options = {} if extract is None else {"extract": extract}
        await extract_material(
            file_id, sessionmaker=sessions, storage=storage, events=events, **options
        )

    return run


async def upload(
    client: AsyncClient, project: Project, *files: tuple[str, bytes], folder: str = "materials"
) -> None:
    parts = [("files", (name, data)) for name, data in files]
    response = await client.post(
        f"/api/v1/projects/{project['id']}/upload", files=parts, data={"dir": folder}
    )
    assert response.status_code == 200, response.text


async def file_id(session: AsyncSession, project: Project, path: str) -> uuid.UUID:
    found = await session.scalar(
        select(File.id).where(File.project_id == uuid.UUID(project["id"]), File.path == path)
    )
    assert found is not None
    return found


async def row(session: AsyncSession, id_: uuid.UUID) -> MaterialText | None:
    return await session.scalar(
        select(MaterialText)
        .where(MaterialText.file_id == id_)
        .execution_options(populate_existing=True)
    )


def material_events(events: FakeEvents) -> list[MaterialReadyData]:
    return [
        event.data
        for event in events.published
        if event.type == EventType.MATERIAL_READY and isinstance(event.data, MaterialReadyData)
    ]


async def test_every_write_that_makes_material_pending_wakes_extraction(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    extractions: list[uuid.UUID],
) -> None:
    pid = project["id"]
    await upload(user_client, project, ("task.pdf", make_pdf(["v1"])), ("main.py", b"x = 1\n"))
    await upload(user_client, project, ("code.py", b"print(1)\n"), folder="")
    task = await file_id(db_session, project, "materials/task.pdf")
    main = await file_id(db_session, project, "materials/main.py")
    # Исходник вне materials/ — не материал.
    assert extractions == [task, main]

    # Запись текста в materials/ и перенос туда.
    await user_client.put(f"/api/v1/projects/{pid}/files/materials/notes.md", content="# Итог")
    notes = await file_id(db_session, project, "materials/notes.md")
    code = await file_id(db_session, project, "code.py")
    await user_client.post(
        f"/api/v1/projects/{pid}/move", json={"from": "code.py", "to": "materials/code.py"}
    )
    assert extractions == [task, main, notes, code]

    # Перенос внутри materials/ текст сохраняет — извлекать заново нечего.
    await user_client.post(
        f"/api/v1/projects/{pid}/move", json={"from": "materials/notes.md", "to": "materials/n.md"}
    )
    assert extractions == [task, main, notes, code]

    # Откат загрузки новой версии возвращает прежнее содержимое — текст извлекается заново.
    await backdate_changesets(db_session, uuid.UUID(pid))
    await upload(user_client, project, ("task.pdf", make_pdf(["v2"])))
    latest = await db_session.scalar(
        select(Changeset.id)
        .where(Changeset.project_id == uuid.UUID(pid))
        .order_by(Changeset.created_at.desc())
        .limit(1)
    )
    reverted = await user_client.post(f"/api/v1/changesets/{latest}/revert")
    assert reverted.status_code == 201, reverted.text
    assert extractions == [task, main, notes, code, task, task]


async def test_pdf_text_is_saved_and_material_ready_sent(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    events: FakeEvents,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("task.pdf", make_pdf(["Goal", "Steps"])))
    task = await file_id(db_session, project, "materials/task.pdf")

    await run_job(task)

    saved = await row(db_session, task)
    assert saved is not None
    assert (saved.status, saved.method, saved.pages, saved.error) == ("ready", "pdfminer", 2, None)
    assert saved.text == "<!-- Страница 1 -->\nGoal\n\n<!-- Страница 2 -->\nSteps"
    assert material_events(events) == [MaterialReadyData(path="materials/task.pdf", status="ready")]


async def test_text_material_is_kept_as_is(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("data.csv", b"t;U\n1;5\n"))
    data = await file_id(db_session, project, "materials/data.csv")

    await run_job(data)

    saved = await row(db_session, data)
    assert saved is not None
    assert (saved.status, saved.method, saved.text) == ("ready", "text", "t;U\n1;5\n")


async def test_failure_is_saved_with_message_and_event(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    events: FakeEvents,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("scheme.svg", SVG))
    scheme = await file_id(db_session, project, "materials/scheme.svg")

    await run_job(scheme)

    saved = await row(db_session, scheme)
    assert saved is not None
    assert (saved.status, saved.text, saved.method, saved.error) == (
        "failed",
        None,
        None,
        SVG_MESSAGE,
    )
    assert material_events(events) == [
        MaterialReadyData(path="materials/scheme.svg", status="failed")
    ]


async def test_crash_in_extraction_fails_instead_of_staying_pending(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("task.pdf", make_pdf(["x"])))
    task = await file_id(db_session, project, "materials/task.pdf")

    async def broken(mime: str | None, content: str | bytes) -> Extracted:
        raise RuntimeError("ошибка в коде")

    await run_job(task, broken)

    saved = await row(db_session, task)
    assert saved is not None
    assert (saved.status, saved.error) == ("failed", FAILED_MESSAGE)


async def test_lost_blob_fails_with_reupload_advice(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    storage: LocalStorage,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("task.docx", make_docx(["Задание"])))
    task = await file_id(db_session, project, "materials/task.docx")
    sha = await db_session.scalar(select(File.blob_sha256).where(File.id == task))
    assert sha is not None
    await storage.delete(sha)

    await run_job(task)

    saved = await row(db_session, task)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.error is not None
    assert "Загрузите его ещё раз" in saved.error


async def test_repeated_job_changes_nothing(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    events: FakeEvents,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("notes.txt", "Вывод: 42".encode()))
    notes = await file_id(db_session, project, "materials/notes.txt")
    await run_job(notes)
    first = await row(db_session, notes)
    assert first is not None
    finished_at = first.updated_at

    await run_job(notes)

    again = await row(db_session, notes)
    assert again is not None
    assert (again.status, again.updated_at) == ("ready", finished_at)
    assert len(material_events(events)) == 1


async def test_new_version_during_extraction_discards_old_text(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    events: FakeEvents,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("notes.txt", b"old"))
    notes = await file_id(db_session, project, "materials/notes.txt")

    async def replaced_meanwhile(mime: str | None, content: str | bytes) -> Extracted:
        await upload(user_client, project, ("notes.txt", b"new"))
        return Extracted(text=str(content), pages=None, method="text")

    await run_job(notes, replaced_meanwhile)

    # Текст старой версии не записан: новая ждёт своего задания.
    waiting = await row(db_session, notes)
    assert waiting is not None
    assert (waiting.status, waiting.text) == ("pending", None)
    assert material_events(events) == []

    await run_job(notes)

    done = await row(db_session, notes)
    assert done is not None
    assert (done.status, done.text) == ("ready", "new")


async def test_duplicate_job_during_extraction_wins_and_sends_one_event(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    events: FakeEvents,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("notes.txt", b"text"))
    notes = await file_id(db_session, project, "materials/notes.txt")

    async def duplicate_meanwhile(mime: str | None, content: str | bytes) -> Extracted:
        # Задание пришло ещё раз и успело раньше: итог первого больше не нужен.
        await run_job(notes)
        return Extracted(text="from the first job", pages=None, method="text")

    await run_job(notes, duplicate_meanwhile)

    saved = await row(db_session, notes)
    assert saved is not None
    assert (saved.status, saved.text) == ("ready", "text")
    assert len(material_events(events)) == 1


async def test_rename_during_extraction_reports_new_path(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    events: FakeEvents,
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("notes.txt", b"text"))
    notes = await file_id(db_session, project, "materials/notes.txt")

    async def renamed_meanwhile(mime: str | None, content: str | bytes) -> Extracted:
        await user_client.post(
            f"/api/v1/projects/{project['id']}/move",
            json={"from": "materials/notes.txt", "to": "materials/lab/notes.txt"},
        )
        return Extracted(text=str(content), pages=None, method="text")

    await run_job(notes, renamed_meanwhile)

    assert material_events(events) == [
        MaterialReadyData(path="materials/lab/notes.txt", status="ready")
    ]


@pytest.mark.parametrize(
    "gone",
    [
        ("DELETE", "/files/materials/notes.txt", None),
        ("POST", "/move", {"from": "materials/notes.txt", "to": "notes.txt"}),
        ("DELETE", "", None),
    ],
    ids=["file-deleted", "moved-out-of-materials", "project-deleted"],
)
async def test_material_gone_during_extraction_is_skipped(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    events: FakeEvents,
    run_job: Callable[..., Awaitable[None]],
    gone: tuple[str, str, dict[str, str] | None],
) -> None:
    await upload(user_client, project, ("notes.txt", b"text"))
    notes = await file_id(db_session, project, "materials/notes.txt")
    method, suffix, body = gone

    async def gone_meanwhile(mime: str | None, content: str | bytes) -> Extracted:
        response = await user_client.request(
            method, f"/api/v1/projects/{project['id']}{suffix}", json=body
        )
        assert response.status_code in (200, 204), response.text
        return Extracted(text=str(content), pages=None, method="text")

    await run_job(notes, gone_meanwhile)

    assert await row(db_session, notes) is None
    assert material_events(events) == []


async def test_sweep_requeues_only_long_waiting_materials_once(
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    sessions: async_sessionmaker[AsyncSession],
    run_job: Callable[..., Awaitable[None]],
) -> None:
    await upload(user_client, project, ("lost.txt", b"a"), ("fresh.txt", b"b"), ("done.txt", b"c"))
    lost, _fresh, done = [
        await file_id(db_session, project, f"materials/{name}.txt")
        for name in ("lost", "fresh", "done")
    ]
    await run_job(done)
    await db_session.execute(
        update(MaterialText)
        .where(MaterialText.file_id.in_([lost, done]))
        .values(updated_at=MaterialText.updated_at - timedelta(minutes=3))
    )
    sent: list[list[uuid.UUID]] = []

    async def enqueue(file_ids: list[uuid.UUID]) -> None:
        sent.append(list(file_ids))

    await tasks.sweep_materials(sessions, enqueue)
    await tasks.sweep_materials(sessions, enqueue)

    # Свежий ещё ждёт своего задания, готовый не нужен, а отправленный не уходит дважды.
    assert sent == [[lost]]
    await run_job(lost)
    saved = await row(db_session, lost)
    assert saved is not None
    assert saved.status == "ready"


async def test_unavailable_queue_does_not_break_upload(
    app: Any,
    user_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[uuid.UUID] = []

    async def unavailable(file_id: uuid.UUID) -> None:
        calls.append(file_id)
        raise SendTaskError()

    monkeypatch.setattr(tasks.extract_material_job, "kiq", unavailable)
    app.dependency_overrides[get_extract_materials] = lambda: tasks.enqueue_extraction

    await upload(user_client, project, ("a.txt", b"a"), ("b.txt", b"b"))

    # Загрузка сохранена; после первой ошибки очередь больше не ждут — материалы
    # отправит фоновая проверка.
    a = await file_id(db_session, project, "materials/a.txt")
    assert calls == [a]
    saved = await row(db_session, a)
    assert saved is not None
    assert saved.status == "pending"


async def test_slow_queue_is_waited_for_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def hang(file_id: uuid.UUID) -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(10)

    monkeypatch.setattr(tasks.extract_material_job, "kiq", hang)
    monkeypatch.setattr(tasks, "ENQUEUE_TIMEOUT_S", 0.05)

    await tasks.enqueue_extraction([uuid.uuid4(), uuid.uuid4()])

    assert calls == 1
