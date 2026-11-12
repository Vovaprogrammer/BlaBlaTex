"""GET /projects/{pid}/template-guide — справка шаблона для агента (architecture.md 9.1).

Агент по токену получает то же, что get_template_guide у ИИ на сайте (9.4), и пишет отчёт
по тем же правилам.
"""

import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.templates import service as templates_service
from tests.helpers import SignUp
from tests.test_bearer_auth import issue_token, use_token

Json = dict[str, Any]


def guide_url(project: Json) -> str:
    return f"/api/v1/projects/{project['id']}/template-guide"


async def test_guide_is_what_site_ai_gets(
    app: FastAPI, user_client: AsyncClient, project: Json
) -> None:
    response = await user_client.get(guide_url(project))

    assert response.status_code == 200, response.text
    manifest = app.state.templates["test-lab"].manifest
    expected = templates_service.template_guide(manifest, project["fields"])
    assert response.json() == expected.model_dump(mode="json")
    guide = response.json()
    # То, чего нет в GET /templates/{slug}: правила шаблона, макросы полей и класса.
    assert guide["ai_rules"] == manifest.ai_rules
    assert {field["key"]: field["macro"] for field in guide["fields"]}["lab_number"] == (
        "\\bbtLabNumber"
    )
    assert any(macro["usage"].startswith("\\bbtScreenshot") for macro in guide["macros"])
    assert all(section["guide"] for section in guide["sections"])


async def test_guide_by_token(user_client: AsyncClient, project: Json) -> None:
    by_cookie = (await user_client.get(guide_url(project))).json()
    token = await issue_token(user_client)
    use_token(user_client, token["token"])

    response = await user_client.get(guide_url(project))

    assert response.status_code == 200, response.text
    assert response.json() == by_cookie


async def test_guide_follows_project_fields(user_client: AsyncClient, project: Json) -> None:
    response = await user_client.patch(
        f"/api/v1/projects/{project['id']}", json={"fields": {**project["fields"], "lab_number": 7}}
    )
    assert response.status_code == 200, response.text

    guide = (await user_client.get(guide_url(project))).json()

    assert {field["key"]: field["value"] for field in guide["fields"]}["lab_number"] == 7


async def test_guide_of_foreign_project_is_not_found(
    user_client: AsyncClient, project: Json, sign_up: SignUp
) -> None:
    await sign_up("petrov@example.com")

    response = await user_client.get(guide_url(project))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_guide_of_removed_template_is_not_found(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project).where(Project.id == uuid.UUID(project["id"])).values(template_slug="gone")
    )

    response = await user_client.get(guide_url(project))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == templates_service.TEMPLATE_GONE_MESSAGE
