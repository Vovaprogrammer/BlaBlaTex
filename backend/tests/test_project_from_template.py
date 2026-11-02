"""Проект из шаблона: файлы шаблона, значения из манифеста и проверка полей по нему."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.auth import service as auth_service
from app.modules.projects import service as projects_service
from app.modules.templates.dependencies import get_templates
from app.modules.templates.registry import load_templates
from app.modules.templates.service import validate_fields
from tests.helpers import TEMPLATE_FIXTURES, TEST_TEMPLATES, CreateProject

PROJECTS = "/api/v1/projects"
# Any — проект и тело запроса как JSON.
Json = dict[str, Any]


async def tree(client: AsyncClient, project: Json) -> list[Json]:
    response = await client.get(f"{PROJECTS}/{project['id']}/tree")
    assert response.status_code == 200
    return list(response.json()["items"])


def errors(response: Response) -> list[tuple[list[str], str]]:
    """Ошибки по полям из ответа 422: (loc, type)."""
    assert response.status_code == 422, response.text
    return [
        (error["loc"], error["type"]) for error in response.json()["error"]["details"]["errors"]
    ]


@pytest.mark.parametrize("slug", list(TEST_TEMPLATES))
async def test_project_gets_template_files(
    user_client: AsyncClient, create_project: CreateProject, slug: str
) -> None:
    template = load_templates(TEMPLATE_FIXTURES)[slug]

    project = await create_project(slug)

    items = await tree(user_client, project)
    files = {item["path"]: item for item in items if item["kind"] == "text"}
    # template.yaml и meta.sample.tex в проект не попадают.
    assert sorted(files) == sorted(template.files)
    assert {item["role"] for item in files.values()} == {"source"}
    for path, text in template.files.items():
        response = await user_client.get(f"{PROJECTS}/{project['id']}/files/{path}")
        assert response.text == text
    folders = [item["path"] for item in items if item["kind"] == "folder"]
    assert folders == sorted({path.rsplit("/", 1)[0] for path in template.files if "/" in path})


async def test_unknown_template_is_validation_error(user_client: AsyncClient) -> None:
    response = await user_client.post(
        PROJECTS, json={"title": "ЛР", "template_slug": "mtuci-lab", "fields": {}}
    )

    assert errors(response) == [(["body", "template_slug"], "value_error")]
    assert response.json()["error"]["details"]["errors"][0]["message"] == "Такого шаблона нет"
    assert (await user_client.get(PROJECTS)).json() == {"items": []}


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"lab_title": "Сортировки"}, [("lab_number", "missing")]),
        ({"lab_number": 1, "lab_title": "   "}, [("lab_title", "missing")]),
        ({"lab_number": "1", "lab_title": "Сортировки"}, [("lab_number", "int_type")]),
        ({"lab_number": 1, "lab_title": 7}, [("lab_title", "string_type")]),
        (
            {"lab_number": 1, "lab_title": "Сортировки", "lab_nomber": 2},
            [("lab_nomber", "extra_forbidden")],
        ),
        ({}, [("lab_number", "missing"), ("lab_title", "missing")]),
    ],
    ids=["missing", "blank", "int as string", "string as int", "unknown", "all at once"],
)
async def test_fields_are_checked_by_template(
    user_client: AsyncClient, fields: Json, expected: list[tuple[str, str]]
) -> None:
    response = await user_client.post(
        PROJECTS, json={"title": "ЛР", "template_slug": "test-lab", "fields": fields}
    )

    assert errors(response) == [(["body", "fields", key], kind) for key, kind in expected]
    assert (await user_client.get(PROJECTS)).json() == {"items": []}


async def test_select_takes_only_options(user_client: AsyncClient) -> None:
    fields = TEST_TEMPLATES["test-vkr"] | {"degree": "аспирант"}

    response = await user_client.post(
        PROJECTS, json={"title": "ВКР", "template_slug": "test-vkr", "fields": fields}
    )

    assert errors(response) == [(["body", "fields", "degree"], "literal_error")]
    message = response.json()["error"]["details"]["errors"][0]["message"]
    assert message == "Выберите один из вариантов: бакалавр, магистр"


async def test_optional_fields_are_kept_as_passed(
    user_client: AsyncClient, create_project: CreateProject
) -> None:
    fields = TEST_TEMPLATES["test-vkr"] | {"degree": "магистр"}
    response = await user_client.post(
        PROJECTS, json={"title": "ВКР", "template_slug": "test-vkr", "fields": fields}
    )
    lab = await create_project("test-lab")

    assert response.json()["fields"] == fields
    # Необязательное поле без default не появляется само.
    assert "variant" not in lab["fields"]


async def test_patch_checks_fields_by_project_template(
    user_client: AsyncClient, project: Json
) -> None:
    url = f"{PROJECTS}/{project['id']}"

    wrong = await user_client.patch(url, json={"fields": {"lab_number": 2}})
    right = await user_client.patch(
        url, json={"fields": {"lab_number": 2, "lab_title": "Поиск", "variant": "3"}}
    )

    assert errors(wrong) == [(["body", "fields", "lab_title"], "missing")]
    assert right.status_code == 200
    assert right.json()["fields"] == {"lab_number": 2, "lab_title": "Поиск", "variant": "3"}


async def test_title_can_change_when_template_is_gone(
    user_client: AsyncClient, project: Json, app: FastAPI
) -> None:
    app.dependency_overrides[get_templates] = lambda: {}
    url = f"{PROJECTS}/{project['id']}"

    renamed = await user_client.patch(url, json={"title": "ЛР 1, новая"})
    refilled = await user_client.patch(url, json={"fields": TEST_TEMPLATES["test-lab"]})

    assert renamed.status_code == 200
    assert errors(refilled) == [(["body", "fields"], "value_error")]


def test_bool_is_not_an_int_field_value() -> None:
    # Схема HTTP отвергает true сама; сервис проверяет и для вызовов не из HTTP.
    manifest = load_templates(TEMPLATE_FIXTURES)["test-lab"].manifest

    with pytest.raises(AppError) as caught:
        validate_fields(manifest, {"lab_number": True, "lab_title": "Сортировки"})

    [error] = caught.value.details["errors"]
    assert error == {
        "loc": ["body", "fields", "lab_number"],
        "type": "int_type",
        "message": "Ожидается целое число",
    }


async def test_template_files_count_toward_project_size_limit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _ = await auth_service.register(db_session, "ivanov@example.com", "password1")
    monkeypatch.setattr(projects_service, "PROJECT_MAX_BYTES", 10)
    new = projects_service.NewProject(
        title="ЛР 1",
        template_slug="test-lab",
        template_version=1,
        kind="lab",
        engine="xelatex",
        main_file="main.tex",
        fields=TEST_TEMPLATES["test-lab"],
    )

    with pytest.raises(AppError) as caught:
        await projects_service.create_project(
            db_session, user.id, new, {"main.tex": "123456", "sections/a.tex": "123456"}
        )

    assert caught.value.status == 413
    assert await projects_service.list_projects(db_session, user.id) == []
