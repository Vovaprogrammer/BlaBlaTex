"""История правок через API (architecture.md 9.1): список changesets, diff и откат."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventType
from app.modules.materials.models import MaterialText
from app.modules.projects import history
from app.modules.projects import service as projects_service
from app.modules.projects.history import Writer
from app.modules.projects.models import Changeset, File, FileRevision
from tests.fake_events import FakeEvents
from tests.file_samples import PNG
from tests.helpers import CreateProject, SignUp, backdate_changesets

# Any — проект, changeset и diff как JSON из ответа API.
Json = dict[str, Any]


def project_url(project: Json) -> str:
    return f"/api/v1/projects/{project['id']}"


async def save(client: AsyncClient, project: Json, path: str, text: str) -> Response:
    response = await client.put(f"{project_url(project)}/files/{path}", content=text.encode())
    assert response.status_code in (200, 201), response.text
    return response


async def read(client: AsyncClient, project: Json, path: str) -> Response:
    return await client.get(f"{project_url(project)}/files/{path}")


async def move(client: AsyncClient, project: Json, from_: str, to: str) -> None:
    response = await client.post(f"{project_url(project)}/move", json={"from": from_, "to": to})
    assert response.status_code == 200, response.text


async def remove(client: AsyncClient, project: Json, path: str) -> None:
    response = await client.delete(f"{project_url(project)}/files/{path}")
    assert response.status_code == 204, response.text


async def paths(client: AsyncClient, project: Json) -> dict[str, str]:
    """Путь → вид у всех файлов и папок проекта."""
    items = (await client.get(f"{project_url(project)}/tree")).json()["items"]
    return {item["path"]: item["kind"] for item in items}


async def changesets(client: AsyncClient, project: Json, **query: str | int) -> Json:
    response = await client.get(f"{project_url(project)}/changesets", params=query)
    assert response.status_code == 200, response.text
    result: Json = response.json()
    return result


async def latest(client: AsyncClient, project: Json) -> Json:
    """Последний changeset проекта."""
    item: Json = (await changesets(client, project))["items"][0]
    return item


async def diff_of(client: AsyncClient, changeset: Json) -> dict[str, Json]:
    """Diff changeset: путь → FileDiff."""
    response = await client.get(f"/api/v1/changesets/{changeset['id']}/diff")
    assert response.status_code == 200, response.text
    return {item["path"]: item for item in response.json()["files"]}


async def revert(client: AsyncClient, changeset: Json) -> Response:
    return await client.post(f"/api/v1/changesets/{changeset['id']}/revert")


async def next_group(session: AsyncSession, project: Json) -> None:
    """Дальше — новый changeset: прошло больше 10 минут склейки."""
    await backdate_changesets(session, uuid.UUID(project["id"]))


async def edit(
    client: AsyncClient, session: AsyncSession, project: Json, path: str, text: str
) -> Json:
    """Правка в отдельном changeset; возвращает этот changeset."""
    await next_group(session, project)
    await save(client, project, path, text)
    return await latest(client, project)


def conflict(response: Response) -> list[tuple[str, str]]:
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "revert_conflict"
    return [(item["path"], item["reason"]) for item in error["details"]["files"]]


# Список


async def test_history_lists_written_changesets_newest_first(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    first = await edit(user_client, db_session, project, "a.tex", "1")
    second = await edit(user_client, db_session, project, "a.tex", "2")
    # Пустой changeset (прогон ИИ, который ничего не записал) в истории не виден.
    db_session.add(Changeset(project_id=uuid.UUID(project["id"]), author="ai"))
    await db_session.flush()

    items = (await changesets(user_client, project))["items"]

    assert [item["id"] for item in items[:2]] == [second["id"], first["id"]]
    assert [item["author"] for item in items] == ["user", "user", "template"]
    assert set(items[0]) == {
        "id",
        "author",
        "message",
        "run_id",
        "reverts_id",
        "reverted_by",
        "created_at",
        "updated_at",
    }


async def test_history_pages(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    for text in ("1", "2", "3"):
        await edit(user_client, db_session, project, "a.tex", text)

    page = await changesets(user_client, project, limit=2)
    rest = await changesets(user_client, project, limit=2, before=page["items"][-1]["id"])

    assert (len(page["items"]), page["has_more"]) == (2, True)
    assert (len(rest["items"]), rest["has_more"]) == (2, False)
    assert rest["items"][-1]["author"] == "template"


async def test_history_cursor_of_other_project_is_rejected(
    user_client: AsyncClient, project: Json, create_project: CreateProject
) -> None:
    other = await create_project(title="ЛР 2")
    foreign = await latest(user_client, other)

    response = await user_client.get(
        f"{project_url(project)}/changesets", params={"before": foreign["id"]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["loc"] == ["query", "before"]


async def test_changesets_of_foreign_project_are_not_found(
    user_client: AsyncClient,
    project: Json,
    sign_up: SignUp,
) -> None:
    mine = await latest(user_client, project)
    await sign_up("petrov@example.com")

    responses = [
        await user_client.get(f"{project_url(project)}/changesets"),
        await user_client.get(f"/api/v1/changesets/{mine['id']}/diff"),
        await revert(user_client, mine),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]


# Diff


async def test_diff_of_edited_text(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "один\nдва\nтри\n")
    changeset = await edit(user_client, db_session, project, "a.tex", "один\n2\nтри\nчетыре\n")

    item = (await diff_of(user_client, changeset))["a.tex"]

    assert (item["change"], item["kind"], item["old_path"]) == ("modified", "text", None)
    assert (item["additions"], item["deletions"], item["too_large"]) == (2, 1, False)
    assert item["diff"].splitlines() == [
        "--- a/a.tex",
        "+++ b/a.tex",
        "@@ -1,3 +1,4 @@",
        " один",
        "-два",
        "+2",
        " три",
        "+четыре",
    ]


async def test_diff_of_new_and_deleted_files(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "old.tex", "прощай")
    await next_group(db_session, project)
    await save(user_client, project, "new/one.tex", "привет\n")
    await remove(user_client, project, "old.tex")

    files = await diff_of(user_client, await latest(user_client, project))

    assert set(files) == {"new", "new/one.tex", "old.tex"}
    assert (files["new"]["change"], files["new"]["kind"], files["new"]["diff"]) == (
        "added",
        "folder",
        None,
    )
    added, deleted = files["new/one.tex"], files["old.tex"]
    assert added["diff"].startswith("--- /dev/null\n+++ b/new/one.tex\n@@ -0,0 +1 @@\n+привет")
    assert (added["change"], added["additions"], added["deletions"]) == ("added", 1, 0)
    # У последней строки без перевода строки — пометка, как у git.
    assert deleted["diff"].endswith("-прощай\n\\ No newline at end of file\n")
    assert (deleted["change"], deleted["additions"], deleted["deletions"]) == ("deleted", 0, 1)


async def test_diff_of_moves(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "текст\n")
    await save(user_client, project, "b.tex", "старое\n")
    await next_group(db_session, project)
    await move(user_client, project, "a.tex", "parts/a.tex")
    await move(user_client, project, "b.tex", "parts/b.tex")
    await save(user_client, project, "parts/b.tex", "новое\n")

    files = await diff_of(user_client, await latest(user_client, project))

    only_moved, moved_and_edited = files["parts/a.tex"], files["parts/b.tex"]
    assert (only_moved["change"], only_moved["old_path"]) == ("moved", "a.tex")
    assert (only_moved["diff"], only_moved["additions"], only_moved["deletions"]) == (None, 0, 0)
    assert (moved_and_edited["change"], moved_and_edited["old_path"]) == ("moved", "b.tex")
    assert moved_and_edited["diff"].startswith("--- a/b.tex\n+++ b/parts/b.tex\n")
    assert (moved_and_edited["additions"], moved_and_edited["deletions"]) == (1, 1)


async def test_diff_of_picture_has_no_text(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    url = f"{project_url(project)}/upload"
    await user_client.post(url, files=[("files", ("plot.png", PNG))])
    await next_group(db_session, project)
    await user_client.post(url, files=[("files", ("plot.png", PNG + b"\x00"))])

    item = (await diff_of(user_client, await latest(user_client, project)))["plot.png"]

    assert (item["change"], item["kind"], item["diff"], item["too_large"]) == (
        "modified",
        "binary",
        None,
        False,
    )


async def test_edit_undone_within_changeset_is_not_in_diff(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "как было")
    await next_group(db_session, project)
    await save(user_client, project, "a.tex", "черновик")
    await save(user_client, project, "a.tex", "как было")
    await save(user_client, project, "tmp.tex", "x")
    await remove(user_client, project, "tmp.tex")
    await save(user_client, project, "b.tex", "новый")

    files = await diff_of(user_client, await latest(user_client, project))

    assert set(files) == {"b.tex"}


async def test_large_text_and_full_response_are_too_large(
    user_client: AsyncClient,
    project: Json,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    big = "x" * (history.DIFF_FILE_MAX_BYTES + 1)
    await next_group(db_session, project)
    await save(user_client, project, "a-big.txt", big)
    await save(user_client, project, "b.tex", "небольшой\n")
    await save(user_client, project, "c.tex", "не влез\n")
    # Ответ уже набрал b.tex — c.tex в него не влезает.
    monkeypatch.setattr(history, "DIFF_MAX_BYTES", 60)

    files = await diff_of(user_client, await latest(user_client, project))

    assert files["a-big.txt"]["too_large"] is True
    assert files["b.tex"]["diff"] is not None
    assert (files["c.tex"]["too_large"], files["c.tex"]["diff"]) == (True, None)
    assert (files["c.tex"]["additions"], files["c.tex"]["deletions"]) == (0, 0)


async def test_first_edit_after_rollout_has_diff(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    # Проект, созданный до истории правок: ревизий у его файлов нет.
    pid = uuid.UUID(project["id"])
    await db_session.execute(delete(Changeset).where(Changeset.project_id == pid))
    goal = (await read(user_client, project, "sections/goal.tex")).text

    await save(user_client, project, "sections/goal.tex", "Новая цель\n")

    changeset = await latest(user_client, project)
    item = (await diff_of(user_client, changeset))["sections/goal.tex"]
    assert item["change"] == "modified"
    assert f"-{goal.splitlines()[0]}" in item["diff"].splitlines()
    assert (await revert(user_client, changeset)).status_code == 201
    assert (await read(user_client, project, "sections/goal.tex")).text == goal


# Откат


async def test_revert_restores_text_as_new_changeset(
    user_client: AsyncClient, project: Json, db_session: AsyncSession, events: FakeEvents
) -> None:
    before = await save(user_client, project, "a.tex", "до")
    changeset = await edit(user_client, db_session, project, "a.tex", "после")
    events.published.clear()

    response = await revert(user_client, changeset)

    assert response.status_code == 201, response.text
    reverted = response.json()
    assert (reverted["author"], reverted["reverts_id"]) == ("user", changeset["id"])
    restored = await read(user_client, project, "a.tex")
    assert restored.text == "до"
    # Версия — новая: вкладка с «после» получит конфликт, а не перезапишет откат.
    assert int(restored.headers["etag"].strip('"')) > before.json()["version"]
    assert (await latest(user_client, project))["id"] == reverted["id"]
    [event] = events.published
    assert event.type == EventType.FILE_CHANGED
    assert event.data.model_dump()["changeset_id"] == uuid.UUID(reverted["id"])


async def test_revert_removes_created_file_and_its_empty_folder(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await next_group(db_session, project)
    await save(user_client, project, "extra/deep/notes.tex", "x")
    before = await paths(user_client, project)

    response = await revert(user_client, await latest(user_client, project))

    assert response.status_code == 201, response.text
    after = await paths(user_client, project)
    assert set(before) - set(after) == {"extra", "extra/deep", "extra/deep/notes.tex"}


async def test_revert_keeps_created_folder_with_later_files(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    changeset = await edit(user_client, db_session, project, "extra/notes.tex", "x")
    await edit(user_client, db_session, project, "extra/mine.tex", "своё")

    response = await revert(user_client, changeset)

    assert response.status_code == 201, response.text
    after = await paths(user_client, project)
    assert ("extra" in after, "extra/notes.tex" in after, "extra/mine.tex" in after) == (
        True,
        False,
        True,
    )


async def test_revert_brings_back_deleted_folder_picture_and_material(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    url = f"{project_url(project)}/upload"
    await user_client.post(url, files=[("files", ("lab/plot.png", PNG))])
    await user_client.post(
        url, files=[("files", ("lab.py", b"print(1)\n"))], data={"dir": "materials"}
    )
    tree = await paths(user_client, project)
    await next_group(db_session, project)
    await remove(user_client, project, "lab")
    await remove(user_client, project, "materials")

    response = await revert(user_client, await latest(user_client, project))

    assert response.status_code == 201, response.text
    assert await paths(user_client, project) == tree
    assert (await read(user_client, project, "lab/plot.png")).content == PNG
    assert (await read(user_client, project, "materials/lab.py")).text == "print(1)\n"
    # Материал вернулся — его текст снова нужно извлечь.
    material = await db_session.scalar(
        select(MaterialText.status)
        .join(File, File.id == MaterialText.file_id)
        .where(File.project_id == uuid.UUID(project["id"]), File.path == "materials/lab.py")
    )
    assert material == "pending"


async def test_restored_file_keeps_its_id(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    pid = uuid.UUID(project["id"])
    await save(user_client, project, "a.tex", "x")
    original = await db_session.scalar(
        select(File.id).where(File.project_id == pid, File.path == "a.tex")
    )
    await next_group(db_session, project)
    await remove(user_client, project, "a.tex")

    await revert(user_client, await latest(user_client, project))

    restored = await db_session.scalar(
        select(File.id).where(File.project_id == pid, File.path == "a.tex")
    )
    assert restored == original


async def test_revert_moves_folder_back(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "s/a.tex", "A")
    await save(user_client, project, "s/in/b.tex", "B")
    tree = await paths(user_client, project)
    await next_group(db_session, project)
    await move(user_client, project, "s", "parts/s")

    response = await revert(user_client, await latest(user_client, project))

    assert response.status_code == 201, response.text
    assert await paths(user_client, project) == tree
    assert (await read(user_client, project, "s/in/b.tex")).text == "B"


async def test_revert_swaps_files_back(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "A")
    await save(user_client, project, "b.tex", "B")
    await next_group(db_session, project)
    await move(user_client, project, "a.tex", "t.tex")
    await move(user_client, project, "b.tex", "a.tex")
    await move(user_client, project, "t.tex", "b.tex")

    response = await revert(user_client, await latest(user_client, project))

    assert response.status_code == 201, response.text
    assert (await read(user_client, project, "a.tex")).text == "A"
    assert (await read(user_client, project, "b.tex")).text == "B"
    assert not any(path.startswith(":") for path in await paths(user_client, project))


async def test_file_changed_after_blocks_revert(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "1")
    await save(user_client, project, "b.tex", "1")
    await next_group(db_session, project)
    await save(user_client, project, "a.tex", "2")
    await save(user_client, project, "b.tex", "2")
    changeset = await latest(user_client, project)
    await edit(user_client, db_session, project, "b.tex", "3")

    response = await revert(user_client, changeset)

    assert conflict(response) == [("b.tex", "changed")]
    assert "b.tex" in response.json()["error"]["message"]
    # Всё или ничего: a.tex тоже не откатился.
    assert (await read(user_client, project, "a.tex")).text == "2"


async def test_taken_place_blocks_revert(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "старый")
    await next_group(db_session, project)
    await remove(user_client, project, "a.tex")
    changeset = await latest(user_client, project)
    await edit(user_client, db_session, project, "a.tex", "новый на том же месте")

    response = await revert(user_client, changeset)

    assert conflict(response) == [("a.tex", "path_taken")]
    assert (await read(user_client, project, "a.tex")).text == "новый на том же месте"


async def test_second_revert_has_nothing_to_do(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    changeset = await edit(user_client, db_session, project, "a.tex", "x")
    assert (await revert(user_client, changeset)).status_code == 201

    assert conflict(await revert(user_client, changeset)) == []


async def test_revert_of_revert_brings_changes_back(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "до")
    changeset = await edit(user_client, db_session, project, "a.tex", "после")
    undo = (await revert(user_client, changeset)).json()

    redo = await revert(user_client, undo)

    assert redo.status_code == 201, redo.text
    assert (await read(user_client, project, "a.tex")).text == "после"


async def test_step_back_twice(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "1")
    first = await edit(user_client, db_session, project, "a.tex", "2")
    second = await edit(user_client, db_session, project, "a.tex", "3")

    # Сначала последние правки, потом предыдущие: файл снова такой, каким его оставил first.
    assert (await revert(user_client, second)).status_code == 201
    response = await revert(user_client, first)

    assert response.status_code == 201, response.text
    assert (await read(user_client, project, "a.tex")).text == "1"


async def reverted_by(client: AsyncClient, changeset: Json) -> str | None:
    response = await client.get(f"/api/v1/changesets/{changeset['id']}/diff")
    assert response.status_code == 200, response.text
    value: str | None = response.json()["changeset"]["reverted_by"]
    return value


async def test_reverted_changeset_shows_its_revert_after_reload(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    changeset = await edit(user_client, db_session, project, "a.tex", "x")
    assert await reverted_by(user_client, changeset) is None

    undo = (await revert(user_client, changeset)).json()

    assert undo["reverted_by"] is None
    assert await reverted_by(user_client, changeset) == undo["id"]
    items = {item["id"]: item for item in (await changesets(user_client, project))["items"]}
    assert items[changeset["id"]]["reverted_by"] == undo["id"]
    assert items[undo["id"]]["reverted_by"] is None


async def test_revert_of_revert_puts_changes_back_in_place(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "до")
    changeset = await edit(user_client, db_session, project, "a.tex", "после")
    undo = (await revert(user_client, changeset)).json()
    redo = (await revert(user_client, undo)).json()

    assert await reverted_by(user_client, changeset) is None
    assert await reverted_by(user_client, undo) == redo["id"]

    # Правки снова на месте — их можно откатить ещё раз, и действует новый откат.
    again = await revert(user_client, changeset)
    assert again.status_code == 201, again.text
    assert await reverted_by(user_client, changeset) == again.json()["id"]


async def test_new_edit_after_revert_starts_new_changeset(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    changeset = await edit(user_client, db_session, project, "a.tex", "x")
    undo = (await revert(user_client, changeset)).json()

    await save(user_client, project, "b.tex", "дальше")

    newest = await latest(user_client, project)
    assert newest["id"] not in (undo["id"], changeset["id"])
    assert newest["reverts_id"] is None


async def test_template_and_meta_changesets_are_not_reverted(
    user_client: AsyncClient, project: Json
) -> None:
    template = await latest(user_client, project)
    fields = {"lab_number": 2, "lab_title": "Графы"}
    await user_client.patch(project_url(project), json={"fields": fields})
    system = await latest(user_client, project)

    responses = [await revert(user_client, template), await revert(user_client, system)]

    assert (template["author"], system["author"]) == ("template", "system")
    assert [response.status_code for response in responses] == [403, 403]


async def test_revert_over_project_limit(
    user_client: AsyncClient,
    project: Json,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await save(user_client, project, "a.tex", "x" * 100)
    changeset = await edit(user_client, db_session, project, "a.tex", "")
    used = sum(
        item["size"]
        for item in (await user_client.get(f"{project_url(project)}/tree")).json()["items"]
    )
    monkeypatch.setattr(projects_service, "PROJECT_MAX_BYTES", used + 50)

    response = await revert(user_client, changeset)

    assert response.status_code == 413
    assert (await read(user_client, project, "a.tex")).text == ""


async def test_user_reverts_ai_changeset(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    pid = uuid.UUID(project["id"])
    await save(user_client, project, "a.tex", "студент")
    run = Changeset(project_id=pid, author="ai")
    db_session.add(run)
    await db_session.flush()
    ai = Writer(FakeEvents(), "ai", None, run.id)
    await projects_service.write_text_file(db_session, ai, pid, "a.tex", "ИИ")
    await projects_service.write_text_file(db_session, ai, pid, "new.tex", "от ИИ")

    response = await user_client.post(f"/api/v1/changesets/{run.id}/revert")

    assert response.status_code == 201, response.text
    assert (await read(user_client, project, "a.tex")).text == "студент"
    assert (await read(user_client, project, "new.tex")).status_code == 404
    kept = await db_session.scalars(
        select(FileRevision.changeset_id).where(FileRevision.changeset_id == run.id)
    )
    # История ИИ не переписывается: откат — отдельный changeset.
    assert len(list(kept)) == 2


async def test_diff_of_new_empty_file_has_headers(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    changeset = await edit(user_client, db_session, project, "empty.tex", "")

    item = (await diff_of(user_client, changeset))["empty.tex"]

    assert (item["change"], item["diff"]) == ("added", "--- /dev/null\n+++ b/empty.tex\n")
    assert (item["additions"], item["deletions"]) == (0, 0)


async def test_revert_frees_place_taken_by_folder_it_moved(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await save(user_client, project, "a.tex", "файл")
    await save(user_client, project, "drafts/x.tex", "черновик")
    tree = await paths(user_client, project)
    await next_group(db_session, project)
    # Файл удалён, а на его место переименована папка: откат вернёт и то и другое.
    await remove(user_client, project, "a.tex")
    await move(user_client, project, "drafts", "a.tex")

    response = await revert(user_client, await latest(user_client, project))

    assert response.status_code == 201, response.text
    assert await paths(user_client, project) == tree
    assert (await read(user_client, project, "a.tex")).text == "файл"


async def test_revert_of_folder_rename_moves_same_folder_back(
    user_client: AsyncClient, project: Json, db_session: AsyncSession, events: FakeEvents
) -> None:
    pid = uuid.UUID(project["id"])
    await save(user_client, project, "s/a.tex", "A")
    folder = select(File.id).where(File.project_id == pid, File.path == "s")
    before = await db_session.scalar(folder)
    await next_group(db_session, project)
    await move(user_client, project, "s", "t")
    events.published.clear()

    response = await revert(user_client, await latest(user_client, project))

    assert response.status_code == 201, response.text
    assert await db_session.scalar(folder) == before
    moved = [
        event.data.model_dump(mode="json", exclude={"changeset_id"})
        for event in events.published
        if event.type == EventType.FILE_MOVED
    ]
    assert {"from": "t", "to": "s"} in moved
