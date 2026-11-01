"""Файлы проекта через HTTP: дерево, чтение и запись с версиями, папки, перенос, удаление."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.modules.projects.service import TEXT_FILE_MAX_BYTES
from tests.conftest import STUDENT_EMAIL, SignUp

# Any — проект как JSON из ответа API.
Project = dict[str, Any]
TEXT = "\\section{Цель работы}\nИзучить сортировки.\n"


def file_url(project: Project, path: str) -> str:
    return f"/api/v1/projects/{project['id']}/files/{path}"


async def tree(client: AsyncClient, project: Project) -> list[tuple[str, str]]:
    response = await client.get(f"/api/v1/projects/{project['id']}/tree")
    assert response.status_code == 200
    return [(item["path"], item["kind"]) for item in response.json()["items"]]


async def put(
    client: AsyncClient, project: Project, path: str, text: str = TEXT, **headers: str
) -> Response:
    headers = {"Content-Type": "text/plain; charset=utf-8"} | headers
    return await client.put(file_url(project, path), content=text.encode(), headers=headers)


async def test_new_project_has_empty_tree(user_client: AsyncClient, project: Project) -> None:
    assert await tree(user_client, project) == []


async def test_create_and_read_text_file(user_client: AsyncClient, project: Project) -> None:
    created = await put(user_client, project, "main.tex", **{"If-None-Match": "*"})

    assert created.status_code == 201
    assert created.headers["ETag"] == '"1"'
    info = created.json()
    assert info | {"updated_at": None} == {
        "path": "main.tex",
        "kind": "text",
        "role": "source",
        "mime": "text/plain",
        "size": len(TEXT.encode()),
        "version": 1,
        "updated_at": None,
    }
    response = await user_client.get(file_url(project, "main.tex"))
    assert response.status_code == 200
    assert response.text == TEXT
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.headers["ETag"] == '"1"'


async def test_put_creates_parent_folders(user_client: AsyncClient, project: Project) -> None:
    await put(user_client, project, "main.tex")

    response = await put(user_client, project, "sections/lab/goal.tex")
    await put(user_client, project, "sections/conclusion.tex")

    assert response.status_code == 201
    assert await tree(user_client, project) == [
        ("main.tex", "text"),
        ("sections", "folder"),
        ("sections/conclusion.tex", "text"),
        ("sections/lab", "folder"),
        ("sections/lab/goal.tex", "text"),
    ]


async def test_update_with_current_version(user_client: AsyncClient, project: Project) -> None:
    await put(user_client, project, "main.tex")

    response = await put(user_client, project, "main.tex", "Новый текст", **{"If-Match": '"1"'})

    assert response.status_code == 200
    assert response.headers["ETag"] == '"2"'
    assert response.json()["version"] == 2
    assert response.json()["size"] == len("Новый текст".encode())
    saved = await user_client.get(file_url(project, "main.tex"))
    assert (saved.text, saved.headers["ETag"]) == ("Новый текст", '"2"')


async def test_stale_version_is_conflict(user_client: AsyncClient, project: Project) -> None:
    await put(user_client, project, "main.tex")
    await put(user_client, project, "main.tex", "Правка из другой вкладки", **{"If-Match": '"1"'})

    response = await put(user_client, project, "main.tex", "Старая правка", **{"If-Match": '"1"'})

    assert response.status_code == 412
    assert response.json()["error"] == {
        "code": "file_conflict",
        "message": "Файл изменён в другом месте",
        "details": {"current_version": 2},
    }
    saved = await user_client.get(file_url(project, "main.tex"))
    assert saved.text == "Правка из другой вкладки"


async def test_if_match_on_deleted_file_is_conflict(
    user_client: AsyncClient, project: Project
) -> None:
    response = await put(user_client, project, "main.tex", **{"If-Match": '"3"'})

    assert response.status_code == 412
    assert response.json()["error"]["details"] == {"current_version": None}
    assert await tree(user_client, project) == []


async def test_create_only_when_file_exists(user_client: AsyncClient, project: Project) -> None:
    await put(user_client, project, "main.tex")

    response = await put(user_client, project, "main.tex", "Другой", **{"If-None-Match": "*"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_exists"
    assert (await user_client.get(file_url(project, "main.tex"))).text == TEXT


async def test_put_without_preconditions_overwrites(
    user_client: AsyncClient, project: Project
) -> None:
    await put(user_client, project, "main.tex")

    response = await put(user_client, project, "main.tex", "Без проверки версии")

    assert response.status_code == 200
    assert response.json()["version"] == 2


@pytest.mark.parametrize(
    ("existing", "path"),
    [
        ("sections/goal.tex", "sections"),  # на месте файла — папка
        ("main.tex", "main.tex/goal.tex"),  # на месте папки — файл
    ],
)
async def test_file_and_folder_cannot_share_path(
    user_client: AsyncClient, project: Project, existing: str, path: str
) -> None:
    await put(user_client, project, existing)
    before = await tree(user_client, project)

    response = await put(user_client, project, path)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_exists"
    assert await tree(user_client, project) == before


@pytest.mark.parametrize("path", ["missing.tex", "sections"])
async def test_read_missing_file_or_folder(
    user_client: AsyncClient, project: Project, path: str
) -> None:
    await put(user_client, project, "sections/goal.tex")

    response = await user_client.get(file_url(project, path))

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Файл не найден",
        "details": {},
    }


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (b"x" * (TEXT_FILE_MAX_BYTES + 1), 413, "payload_too_large"),
        ("Цель".encode("cp1251"), 422, "validation_error"),
        (b"a\x00b", 422, "validation_error"),
    ],
    ids=["too-large", "not-utf8", "nul"],
)
async def test_bad_text_body(
    user_client: AsyncClient, project: Project, body: bytes, status: int, code: str
) -> None:
    response = await user_client.put(file_url(project, "main.tex"), content=body)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert await tree(user_client, project) == []


async def test_text_of_exactly_max_size_is_accepted(
    user_client: AsyncClient, project: Project
) -> None:
    response = await put(user_client, project, "big.txt", "я" * (TEXT_FILE_MAX_BYTES // 2))

    assert response.status_code == 201
    assert response.json()["size"] == TEXT_FILE_MAX_BYTES


@pytest.mark.parametrize(
    ("headers", "loc"),
    [
        ({"If-Match": "1"}, ["header", "if-match"]),
        ({"If-Match": 'W/"1"'}, ["header", "if-match"]),
        ({"If-None-Match": '"1"'}, ["header", "if-none-match"]),
    ],
)
async def test_bad_precondition_header(
    user_client: AsyncClient, project: Project, headers: dict[str, str], loc: list[str]
) -> None:
    await put(user_client, project, "main.tex")

    response = await put(user_client, project, "main.tex", "Новый", **headers)

    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["error"]["details"]["errors"]] == [loc]


@pytest.mark.parametrize("path", ["%2E%2E/secret.tex", ".latexmkrc", "a%5Cb.tex", "latexmkrc", ""])
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_bad_path_in_url(
    user_client: AsyncClient, project: Project, method: str, path: str
) -> None:
    response = await user_client.request(method, file_url(project, path), content=b"x")

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(["path", "path"], "invalid_path")]


async def test_path_is_stored_in_nfc(user_client: AsyncClient, project: Project) -> None:
    await put(user_client, project, "й.tex")

    response = await user_client.get(file_url(project, "й.tex"))

    assert response.status_code == 200
    assert await tree(user_client, project) == [("й.tex", "text")]


async def test_foreign_project_files_are_not_found(
    user_client: AsyncClient, project: Project, sign_up: SignUp
) -> None:
    await put(user_client, project, "main.tex")
    await sign_up("petrov@example.com")

    responses = [
        await user_client.get(f"/api/v1/projects/{project['id']}/tree"),
        await user_client.get(file_url(project, "main.tex")),
        await put(user_client, project, "main.tex", "Чужая правка"),
        await put(user_client, project, "new.tex"),
        await user_client.delete(file_url(project, "main.tex")),
        await user_client.post(folders_url(project), json={"path": "sections"}),
        await user_client.post(move_url(project), json={"from": "main.tex", "to": "x.tex"}),
    ]

    assert [r.status_code for r in responses] == [404] * 7
    assert {r.json()["error"]["message"] for r in responses} == {"Проект не найден"}
    user_client.cookies.clear()
    await user_client.post(
        "/api/v1/auth/login", json={"email": STUDENT_EMAIL, "password": "password1"}
    )
    assert await tree(user_client, project) == [("main.tex", "text")]
    assert (await user_client.get(file_url(project, "main.tex"))).text == TEXT


# Папки, перенос и удаление.


def folders_url(project: Project) -> str:
    return f"/api/v1/projects/{project['id']}/folders"


def move_url(project: Project) -> str:
    return f"/api/v1/projects/{project['id']}/move"


async def move(client: AsyncClient, project: Project, from_: str, to: str) -> Response:
    return await client.post(move_url(project), json={"from": from_, "to": to})


# Имена с _ и похожими префиксами: _ в SQL LIKE совпадает с любым символом,
# а префикс «s_c» без / совпал бы и с «s_c2».
NESTED = ["s_c/a.tex", "s_c/sub/b.tex", "sXc/c.tex", "s_c2/d.tex"]
NEIGHBOURS = [("sXc", "folder"), ("sXc/c.tex", "text"), ("s_c2", "folder"), ("s_c2/d.tex", "text")]


async def test_create_folder_with_parents(user_client: AsyncClient, project: Project) -> None:
    response = await user_client.post(folders_url(project), json={"path": "materials/screens"})

    assert response.status_code == 201
    assert response.json() | {"updated_at": None} == {
        "path": "materials/screens",
        "kind": "folder",
        "role": "source",
        "mime": None,
        "size": 0,
        "version": 1,
        "updated_at": None,
    }
    assert await tree(user_client, project) == [
        ("materials", "folder"),
        ("materials/screens", "folder"),
    ]


@pytest.mark.parametrize("path", ["sections", "sections/goal.tex", "sections/goal.tex/x"])
async def test_create_folder_on_taken_path(
    user_client: AsyncClient, project: Project, path: str
) -> None:
    await put(user_client, project, "sections/goal.tex")
    before = await tree(user_client, project)

    response = await user_client.post(folders_url(project), json={"path": path})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_exists"
    assert await tree(user_client, project) == before


async def test_rename_file_keeps_content_and_version(
    user_client: AsyncClient, project: Project
) -> None:
    await put(user_client, project, "main.tex")
    await put(user_client, project, "main.tex", "Вторая версия", **{"If-Match": '"1"'})

    response = await move(user_client, project, "main.tex", "report.tex")

    assert response.status_code == 200
    assert (response.json()["path"], response.json()["version"]) == ("report.tex", 2)
    assert (await user_client.get(file_url(project, "main.tex"))).status_code == 404
    assert (await user_client.get(file_url(project, "report.tex"))).text == "Вторая версия"
    # Редактор, открывший файл до переименования, сохраняет его без ложного конфликта.
    saved = await put(user_client, project, "report.tex", "Третья", **{"If-Match": '"2"'})
    assert saved.status_code == 200


async def test_move_file_into_new_folder(user_client: AsyncClient, project: Project) -> None:
    await put(user_client, project, "goal.tex")

    response = await move(user_client, project, "goal.tex", "sections/lab/goal.tex")

    assert response.status_code == 200
    assert await tree(user_client, project) == [
        ("sections", "folder"),
        ("sections/lab", "folder"),
        ("sections/lab/goal.tex", "text"),
    ]


async def test_rename_folder_moves_nested_files(user_client: AsyncClient, project: Project) -> None:
    for path in NESTED:
        await put(user_client, project, path, f"Текст {path}")

    response = await move(user_client, project, "s_c", "parts/chapters")

    assert response.status_code == 200
    assert response.json()["path"] == "parts/chapters"
    assert await tree(user_client, project) == [
        ("parts", "folder"),
        ("parts/chapters", "folder"),
        ("parts/chapters/a.tex", "text"),
        ("parts/chapters/sub", "folder"),
        ("parts/chapters/sub/b.tex", "text"),
        *NEIGHBOURS,
    ]
    moved = await user_client.get(file_url(project, "parts/chapters/sub/b.tex"))
    assert (moved.text, moved.headers["ETag"]) == ("Текст s_c/sub/b.tex", '"1"')


@pytest.mark.parametrize(
    ("from_", "to", "status", "code"),
    [
        ("missing.tex", "x.tex", 404, "not_found"),
        ("main.tex", "sections", 409, "already_exists"),
        ("main.tex", "sections/goal.tex", 409, "already_exists"),
        ("sections", "main.tex", 409, "already_exists"),
        ("sections/goal.tex", "main.tex/goal.tex", 409, "already_exists"),
        ("sections", "sections/inner", 422, "validation_error"),
    ],
)
async def test_move_errors(
    user_client: AsyncClient, project: Project, from_: str, to: str, status: int, code: str
) -> None:
    await put(user_client, project, "main.tex")
    await put(user_client, project, "sections/goal.tex")
    before = await tree(user_client, project)

    response = await move(user_client, project, from_, to)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert await tree(user_client, project) == before


async def test_move_folder_into_itself_explains_why(
    user_client: AsyncClient, project: Project
) -> None:
    await user_client.post(folders_url(project), json={"path": "sections"})

    response = await move(user_client, project, "sections", "sections/inner")

    assert response.json()["error"] == {
        "code": "validation_error",
        "message": "Нельзя переместить папку внутрь неё самой",
        "details": {"errors": []},
    }


async def test_move_that_makes_nested_path_too_long(
    user_client: AsyncClient, project: Project
) -> None:
    nested = "a/" + "b" * 100 + "/" + "c" * 100  # 203 символа
    await put(user_client, project, nested)
    before = await tree(user_client, project)

    response = await move(user_client, project, "a", "x" * 60)

    assert response.status_code == 422
    assert "длиннее 255" in response.json()["error"]["message"]
    assert await tree(user_client, project) == before


async def test_move_to_same_path_changes_nothing(
    user_client: AsyncClient, project: Project
) -> None:
    created = await put(user_client, project, "main.tex")

    response = await move(user_client, project, "main.tex", "main.tex")

    assert response.status_code == 200
    assert response.json() == created.json()


async def test_delete_file(user_client: AsyncClient, project: Project) -> None:
    await put(user_client, project, "sections/goal.tex")

    response = await user_client.delete(file_url(project, "sections/goal.tex"))

    assert response.status_code == 204
    assert await tree(user_client, project) == [("sections", "folder")]


async def test_delete_folder_recursively(user_client: AsyncClient, project: Project) -> None:
    for path in NESTED:
        await put(user_client, project, path)

    response = await user_client.delete(file_url(project, "s_c"))

    assert response.status_code == 204
    assert await tree(user_client, project) == NEIGHBOURS
    assert (await user_client.get(file_url(project, "s_c/sub/b.tex"))).status_code == 404


async def test_delete_missing_path(user_client: AsyncClient, project: Project) -> None:
    response = await user_client.delete(file_url(project, "missing.tex"))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Файл или папка не найдены"


@pytest.mark.parametrize(
    ("url", "body", "loc"),
    [
        (folders_url, {"path": ".git"}, ["body", "path"]),
        (move_url, {"from": "../main.tex", "to": "main.tex"}, ["body", "from"]),
        (move_url, {"from": "main.tex", "to": "latexmkrc"}, ["body", "to"]),
    ],
)
async def test_bad_path_in_body(
    user_client: AsyncClient,
    project: Project,
    url: Callable[[Project], str],
    body: dict[str, str],
    loc: list[str],
) -> None:
    response = await user_client.post(url(project), json=body)

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(loc, "invalid_path")]
