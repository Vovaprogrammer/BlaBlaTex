"""Эндпоинты этапа 1 (architecture.md 9.1): все есть в OpenAPI, ошибки — в едином формате."""

from fastapi import FastAPI

# (метод, путь из таблицы 9.1). Все уже работают, их проверяют тесты своих модулей.
STAGE1: list[tuple[str, str]] = [
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/me"),
    ("GET", "/profile"),
    ("PUT", "/profile"),
    ("GET", "/templates"),
    ("GET", "/templates/{slug}"),
    ("GET", "/projects"),
    ("POST", "/projects"),
    ("GET", "/projects/{pid}"),
    ("PATCH", "/projects/{pid}"),
    ("DELETE", "/projects/{pid}"),
    ("GET", "/projects/{pid}/tree"),
    ("GET", "/projects/{pid}/files/{path}"),
    ("PUT", "/projects/{pid}/files/{path}"),
    ("DELETE", "/projects/{pid}/files/{path}"),
    ("POST", "/projects/{pid}/folders"),
    ("POST", "/projects/{pid}/move"),
    ("POST", "/projects/{pid}/builds"),
    ("GET", "/projects/{pid}/builds/latest"),
    ("GET", "/builds/{bid}"),
    ("GET", "/builds/{bid}/pdf"),
    ("GET", "/builds/{bid}/log"),
]


def test_openapi_lists_all_stage1_endpoints(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    missing = [
        f"{method} {path}"
        for method, path in STAGE1
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
