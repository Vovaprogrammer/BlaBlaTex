"""Списки API — по одним правилам (architecture.md 9.1, «Списки»).

Целые списки отдаются одним ответом {items}; история правок и чат — страницами с одними
и теми же before, limit и has_more.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PAGE_MAX_LIMIT
from tests.helpers import CreateProject, backdate_changesets, backdate_project

# Any — JSON из ответа API: его вид проверяют сами тесты.
Json = dict[str, Any]


def project_url(project: Json) -> str:
    return f"/api/v1/projects/{project['id']}"


async def get_json(client: AsyncClient, url: str, **params: str | int) -> Json:
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    result: Json = response.json()
    return result


async def test_whole_lists_are_items_only(user_client: AsyncClient, project: Json) -> None:
    urls = [
        "/api/v1/projects",
        f"{project_url(project)}/tree",
        "/api/v1/templates",
        "/api/v1/tokens",
    ]

    bodies = [await get_json(user_client, url) for url in urls]

    # Ни has_more, ни курсора: агент получает весь список одним запросом.
    assert [set(body) for body in bodies] == [{"items"}] * len(urls)


async def test_whole_lists_keep_documented_order(
    user_client: AsyncClient, create_project: CreateProject, db_session: AsyncSession
) -> None:
    older = await create_project(title="ЛР 1")
    newer = await create_project(title="ЛР 2")
    await backdate_project(db_session, older["id"], hours=1)
    for path in ("b.tex", "a/z.tex", "a.tex"):
        response = await user_client.put(f"{project_url(newer)}/files/{path}", content=b"x")
        assert response.status_code == 201, response.text

    tokens = []
    for name in ("Первый", "Второй"):
        response = await user_client.post("/api/v1/tokens", json={"name": name})
        assert response.status_code == 201, response.text
        tokens.append(response.json()["id"])

    projects = (await get_json(user_client, "/api/v1/projects"))["items"]
    tree = (await get_json(user_client, f"{project_url(newer)}/tree"))["items"]
    templates = (await get_json(user_client, "/api/v1/templates"))["items"]

    assert [item["id"] for item in projects] == [newer["id"], older["id"]]
    paths = [item["path"] for item in tree]
    assert paths == sorted(paths)
    slugs = [item["slug"] for item in templates]
    assert slugs == sorted(slugs)
    listed = (await get_json(user_client, "/api/v1/tokens"))["items"]
    assert [item["id"] for item in listed] == tokens[::-1]


PAGED_LISTS = ["changesets", "messages"]


@pytest.mark.parametrize("name", PAGED_LISTS)
@pytest.mark.parametrize(
    ("params", "field", "message"),
    [
        ({"limit": 0}, "limit", "Значение должно быть не меньше 1"),
        ({"limit": PAGE_MAX_LIMIT + 1}, "limit", "Значение должно быть не больше 100"),
        ({"limit": "abc"}, "limit", "Ожидается целое число"),
        ({"before": "abc"}, "before", "Некорректный идентификатор"),
        ({"before": str(uuid.uuid4())}, "before", None),
    ],
)
async def test_page_params_are_checked_alike(
    user_client: AsyncClient,
    project: Json,
    name: str,
    params: dict[str, str | int],
    field: str,
    message: str | None,
) -> None:
    response = await user_client.get(f"{project_url(project)}/{name}", params=params)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    [detail] = error["details"]["errors"]
    assert detail["loc"] == ["query", field]
    if message is not None:
        assert detail["message"] == message


@pytest.mark.parametrize("name", PAGED_LISTS)
async def test_page_limit_bounds_are_shared(
    user_client: AsyncClient, project: Json, name: str
) -> None:
    for limit in (1, PAGE_MAX_LIMIT):
        body = await get_json(user_client, f"{project_url(project)}/{name}", limit=limit)
        assert {"items", "has_more"} <= set(body)


async def test_history_walks_pages_without_gaps(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    for text in ("1", "2", "3", "4"):
        # Каждая правка — свой changeset: прошлые сдвинуты дальше 10 минут склейки.
        await backdate_changesets(db_session, uuid.UUID(project["id"]))
        response = await user_client.put(f"{project_url(project)}/files/a.tex", content=text)
        assert response.status_code in (200, 201), response.text
    url = f"{project_url(project)}/changesets"
    everything = [item["id"] for item in (await get_json(user_client, url))["items"]]

    walked: list[str] = []
    pages: list[bool] = []
    params: dict[str, str | int] = {"limit": 2}
    while True:
        page = await get_json(user_client, url, **params)
        walked += [item["id"] for item in page["items"]]
        pages.append(page["has_more"])
        if not page["has_more"]:
            break
        params["before"] = page["items"][-1]["id"]

    # Шаблон и 4 правки — 5 changesets: три страницы, без повторов и пропусков.
    assert len(everything) == 5
    assert walked == everything
    assert pages == [True, True, False]
