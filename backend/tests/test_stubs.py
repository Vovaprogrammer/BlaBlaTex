"""Эндпоинты этапа 1 (architecture.md 9.1): пока заглушки, но схемы уже полные."""

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
STAGE1: list[tuple[str, str, dict[str, Any]]] = [
    (
        "POST",
        "/auth/register",
        {"json": {"email": "student@example.com", "password": "password1", "consent": True}},
    ),
    ("POST", "/auth/login", {"json": {"email": "student@example.com", "password": "password1"}}),
    ("POST", "/auth/logout", {}),
    ("GET", "/auth/me", {}),
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


def url(path: str) -> str:
    return "/api/v1" + path.format(pid=PID, bid=BID, slug="mtuci-lab", path=FILE)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"), STAGE1, ids=[f"{m} {p}" for m, p, _ in STAGE1]
)
async def test_stub_answers_not_implemented(
    client: AsyncClient, method: str, path: str, kwargs: dict[str, Any]
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
    me = schema["paths"]["/api/v1/auth/me"]["get"]["responses"]
    log = schema["paths"]["/api/v1/builds/{bid}/log"]["get"]["responses"]

    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert me["default"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    # Успешный ответ — текст, а ошибки всё равно JSON.
    assert list(log["200"]["content"]) == ["text/plain"]
    assert list(log["default"]["content"]) == ["application/json"]


async def test_register_requires_consent(client: AsyncClient) -> None:
    response = await client.post(
        url("/auth/register"),
        json={"email": "student@example.com", "password": "password1", "consent": False},
    )

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(["body", "consent"], "literal_error")]


async def test_register_rejects_short_password_and_bad_email(client: AsyncClient) -> None:
    response = await client.post(
        url("/auth/register"), json={"email": "not-an-email", "password": "short", "consent": True}
    )

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [
        (["body", "email"], "value_error"),
        (["body", "password"], "string_too_short"),
    ]


async def test_invalid_project_id_is_validation_error(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects/not-a-uuid")

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(["path", "pid"], "uuid_parsing")]
