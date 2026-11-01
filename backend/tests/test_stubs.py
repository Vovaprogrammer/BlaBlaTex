"""Эндпоинты этапа 1 (architecture.md 9.1): все есть в OpenAPI, ещё не сделанные отвечают 501."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.errors import NOT_IMPLEMENTED_MESSAGE

PID = uuid4()
BID = uuid4()
FILE = "sections/goal.tex"

PROFILE = {
    "last_name": "Иванов",
    "first_name": "Иван",
    "middle_name": "",
    "group_name": "БВТ2401",
    "faculty": "",
    "department": "",
}

# (метод, путь из таблицы 9.1, аргументы запроса с корректным телом).
# Any — это kwargs для httpx: json, content или headers.
Endpoint = tuple[str, str, dict[str, Any]]

# Уже работают, их проверяют тесты своих модулей.
IMPLEMENTED: list[Endpoint] = [
    ("POST", "/auth/register", {}),
    ("POST", "/auth/login", {}),
    ("POST", "/auth/logout", {}),
    ("GET", "/auth/me", {}),
]
STUBS: list[Endpoint] = [
    ("GET", "/profile", {}),
    ("PUT", "/profile", {"json": PROFILE}),
    ("GET", "/templates", {}),
    ("GET", "/templates/{slug}", {}),
    ("GET", "/projects", {}),
    (
        "POST",
        "/projects",
        {"json": {"title": "ЛР 1", "template_slug": "mtuci-lab", "fields": {"lab_number": 1}}},
    ),
    ("GET", "/projects/{pid}", {}),
    ("PATCH", "/projects/{pid}", {"json": {"title": "ЛР 2"}}),
    ("DELETE", "/projects/{pid}", {}),
    ("GET", "/projects/{pid}/tree", {}),
    ("GET", "/projects/{pid}/files/{path}", {}),
    (
        "PUT",
        "/projects/{pid}/files/{path}",
        {
            "content": "Цель работы".encode(),
            "headers": {"Content-Type": "text/plain; charset=utf-8", "If-Match": '"1"'},
        },
    ),
    ("DELETE", "/projects/{pid}/files/{path}", {}),
    ("POST", "/projects/{pid}/folders", {"json": {"path": "sections"}}),
    ("POST", "/projects/{pid}/move", {"json": {"from": "a.tex", "to": "b.tex"}}),
    ("POST", "/projects/{pid}/builds", {}),
    ("GET", "/projects/{pid}/builds/latest", {}),
    ("GET", "/builds/{bid}", {}),
    ("GET", "/builds/{bid}/pdf", {}),
    ("GET", "/builds/{bid}/log", {}),
]
STAGE1 = IMPLEMENTED + STUBS


def url(path: str) -> str:
    return "/api/v1" + path.format(pid=PID, bid=BID, slug="mtuci-lab", path=FILE)


@pytest.mark.parametrize(("method", "path", "kwargs"), STUBS, ids=[f"{m} {p}" for m, p, _ in STUBS])
async def test_stub_answers_not_implemented(
    client: AsyncClient,
    method: str,
    path: str,
    kwargs: dict[str, Any],  # Any — kwargs для httpx, как в STAGE1
) -> None:
    response = await client.request(method, url(path), **kwargs)

    assert response.status_code == 501
    assert response.json() == {
        "error": {"code": "not_implemented", "message": NOT_IMPLEMENTED_MESSAGE, "details": {}}
    }


def test_openapi_lists_all_stage1_endpoints(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    missing = [
        f"{method} {path}"
        for method, path, _ in STAGE1
        if method.lower() not in paths.get("/api/v1" + path, {})
    ]
    assert missing == []


def test_openapi_documents_errors_in_unified_format(app: FastAPI) -> None:
    schema = app.openapi()
    error_schemas = {
        "422": {"$ref": "#/components/schemas/ValidationErrorResponse"},
        "default": {"$ref": "#/components/schemas/ErrorResponse"},
    }

    assert "HTTPValidationError" not in schema["components"]["schemas"]
    # Ошибки — всегда JSON, даже там, где успешный ответ — текст или PDF.
    wrong = [
        f"{method.upper()} {path} {status}"
        for path, operations in schema["paths"].items()
        if path != "/api/v1/health"
        for method, operation in operations.items()
        for status, expected in error_schemas.items()
        if operation["responses"][status]["content"] != {"application/json": {"schema": expected}}
    ]
    assert wrong == []
    log = schema["paths"]["/api/v1/builds/{bid}/log"]["get"]["responses"]
    assert list(log["200"]["content"]) == ["text/plain"]


async def test_template_field_values_are_not_coerced(client: AsyncClient) -> None:
    response = await client.post(
        url("/projects"),
        json={"title": "ЛР 1", "template_slug": "mtuci-lab", "fields": {"lab_number": True}},
    )

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert {tuple(e["loc"][:3]) for e in errors} == {("body", "fields", "lab_number")}


async def test_invalid_project_id_is_validation_error(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects/not-a-uuid")

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(["path", "pid"], "uuid_parsing")]
