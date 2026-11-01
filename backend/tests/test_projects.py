"""Проекты через HTTP: создание из тестового шаблона, список, изменение, удаление, доступ."""

from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import STUDENT_EMAIL, TEST_TEMPLATES, CreateProject, SignUp

PROJECTS = "/api/v1/projects"
# Any — проект как JSON из ответа API.
Project = dict[str, Any]


@pytest.mark.parametrize("slug", list(TEST_TEMPLATES))
async def test_create_project_from_test_template(
    user_client: AsyncClient, create_project: CreateProject, slug: str
) -> None:
    created = await create_project(slug, title="Отчёт")

    # Пока шаблонов нет, kind, версия, главный файл и движок — значения по умолчанию.
    assert created | {"id": None, "created_at": None, "updated_at": None} == {
        "id": None,
        "title": "Отчёт",
        "kind": "lab",
        "template_slug": slug,
        "template_version": 1,
        "fields": TEST_TEMPLATES[slug],
        "main_file": "main.tex",
        "engine": "xelatex",
        "created_at": None,
        "updated_at": None,
    }
    response = await user_client.get(f"{PROJECTS}/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


async def test_list_shows_own_projects_recently_changed_first(
    user_client: AsyncClient, create_project: CreateProject, sign_up: SignUp
) -> None:
    first = await create_project(title="ЛР 1")
    second = await create_project(title="ЛР 2")
    await user_client.patch(f"{PROJECTS}/{first['id']}", json={"title": "ЛР 1, исправленная"})

    response = await user_client.get(PROJECTS)

    assert response.status_code == 200
    assert [p["id"] for p in response.json()["items"]] == [first["id"], second["id"]]
    await sign_up("petrov@example.com")
    assert (await user_client.get(PROJECTS)).json() == {"items": []}


async def test_patch_changes_only_passed_fields(user_client: AsyncClient, project: Project) -> None:
    url = f"{PROJECTS}/{project['id']}"

    renamed = await user_client.patch(url, json={"title": "ЛР 1 — сортировки", "fields": None})
    refilled = await user_client.patch(url, json={"fields": {"lab_number": 2}})

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "ЛР 1 — сортировки"
    assert renamed.json()["fields"] == project["fields"]
    assert datetime.fromisoformat(renamed.json()["updated_at"]) > datetime.fromisoformat(
        project["updated_at"]
    )
    # fields заменяются целиком, а не дополняются.
    assert refilled.json()["fields"] == {"lab_number": 2}
    assert refilled.json()["title"] == "ЛР 1 — сортировки"
    assert (await user_client.get(url)).json() == refilled.json()


async def test_delete_project(user_client: AsyncClient, project: Project) -> None:
    url = f"{PROJECTS}/{project['id']}"

    response = await user_client.delete(url)

    assert response.status_code == 204
    assert (await user_client.get(url)).status_code == 404
    assert (await user_client.get(PROJECTS)).json() == {"items": []}


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [("GET", {}), ("PATCH", {"json": {"title": "Чужой"}}), ("DELETE", {})],
)
async def test_foreign_project_is_not_found(
    user_client: AsyncClient,
    project: Project,
    sign_up: SignUp,
    method: str,
    kwargs: dict[str, Any],  # Any — kwargs для httpx
) -> None:
    url = f"{PROJECTS}/{project['id']}"
    await sign_up("petrov@example.com")

    foreign = await user_client.request(method, url, **kwargs)
    missing = await user_client.request(method, f"{PROJECTS}/{uuid4()}", **kwargs)

    # Чужой и несуществующий проект неотличимы.
    assert foreign.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["error"]["code"] == "not_found"


async def test_foreign_project_stays_unchanged(
    user_client: AsyncClient, project: Project, sign_up: SignUp
) -> None:
    url = f"{PROJECTS}/{project['id']}"
    await sign_up("petrov@example.com")
    await user_client.patch(url, json={"title": "Чужой"})
    await user_client.delete(url)

    user_client.cookies.clear()
    login = await user_client.post(
        "/api/v1/auth/login", json={"email": STUDENT_EMAIL, "password": "password1"}
    )
    assert login.status_code == 200
    # Владелец видит проект таким же, как до попыток Петрова.
    assert (await user_client.get(url)).json() == project


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "", {}),
        ("POST", "", {"json": {"title": "ЛР", "template_slug": "test-lab", "fields": {}}}),
        ("GET", "/{pid}", {}),
        ("PATCH", "/{pid}", {"json": {"title": "ЛР"}}),
        ("DELETE", "/{pid}", {}),
    ],
)
async def test_projects_require_sign_in(
    db_client: AsyncClient,
    method: str,
    path: str,
    kwargs: dict[str, Any],  # Any — kwargs для httpx
) -> None:
    response = await db_client.request(method, PROJECTS + path.format(pid=uuid4()), **kwargs)

    assert response.status_code == 401


async def test_template_field_values_are_not_coerced(user_client: AsyncClient) -> None:
    response = await user_client.post(
        PROJECTS,
        json={"title": "ЛР 1", "template_slug": "test-lab", "fields": {"lab_number": True}},
    )

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert {tuple(e["loc"][:3]) for e in errors} == {("body", "fields", "lab_number")}


async def test_invalid_project_id_is_validation_error(user_client: AsyncClient) -> None:
    response = await user_client.get(f"{PROJECTS}/not-a-uuid")

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(["path", "pid"], "uuid_parsing")]
