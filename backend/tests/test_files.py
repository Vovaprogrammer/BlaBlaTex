"""Дерево и текстовые файлы проекта через HTTP: чтение, запись, версии, доступ."""

from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.modules.projects.service import TEXT_FILE_MAX_BYTES
from tests.conftest import SignUp

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
@pytest.mark.parametrize("method", ["GET", "PUT"])
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
    ]

    assert [r.status_code for r in responses] == [404] * 4
    assert {r.json()["error"]["message"] for r in responses} == {"Проект не найден"}
