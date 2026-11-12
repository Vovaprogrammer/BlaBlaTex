"""Заголовки безопасности у ответов API и документация в проде (architecture.md 13).

Заголовки файлов, PDF и SVG проверяют свои тесты: test_uploads.py, test_builds_api.py.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

COMMON = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
    "referrer-policy": "no-referrer",
    "cross-origin-resource-policy": "same-origin",
}
JSON_ONLY = {
    "content-security-policy": "default-src 'none'; frame-ancestors 'self'",
    "cache-control": "no-store",
}


async def test_json_answer_and_error_get_all_headers(db_client: AsyncClient) -> None:
    ok = await db_client.get("/api/v1/health")
    error = await db_client.get("/api/v1/auth/me")

    assert ok.status_code == 200
    assert error.status_code == 401
    for response in (ok, error):
        assert {name: response.headers.get(name) for name in COMMON} == COMMON
        assert {name: response.headers.get(name) for name in JSON_ONLY} == JSON_ONLY


async def test_own_headers_of_handler_are_kept(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/api/v1/test-own-headers")
    async def own() -> JSONResponse:
        return JSONResponse({}, headers={"Cache-Control": "max-age=60", "X-Frame-Options": "DENY"})

    response = await client.get("/api/v1/test-own-headers")

    assert response.headers["cache-control"] == "max-age=60"
    assert response.headers["x-frame-options"] == "DENY"
    # Один заголовок, а не два: свой не дописывается рядом.
    assert response.headers.get_list("x-frame-options") == ["DENY"]
    assert response.headers["content-security-policy"] == JSON_ONLY["content-security-policy"]


async def test_docs_work_in_dev_without_csp(client: AsyncClient) -> None:
    docs = await client.get("/api/docs")
    schema = await client.get("/api/openapi.json")

    assert docs.status_code == 200
    assert docs.headers["content-type"].startswith("text/html")
    # Swagger UI грузит скрипты с CDN — строгий CSP JSON его сломал бы.
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-frame-options"] == "SAMEORIGIN"
    assert schema.status_code == 200


async def test_docs_are_off_in_prod(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"app_env": "prod"}))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        docs = await client.get("/api/docs")
        schema = await client.get("/api/openapi.json")

    assert docs.status_code == 404
    assert schema.status_code == 404
    assert docs.headers["x-content-type-options"] == "nosniff"
