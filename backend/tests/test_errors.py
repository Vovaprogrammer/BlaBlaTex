from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field
from structlog.testing import capture_logs

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app


class SignupBody(BaseModel):
    email: str
    password: str = Field(min_length=8)
    age: int


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Настоящее приложение плюс маршруты, которые бросают ошибки разных видов."""
    app = create_app(settings)

    @app.get("/test/conflict")
    async def conflict() -> None:
        raise AppError(
            ErrorCode.FILE_CONFLICT, "Файл изменён в другом месте", 412, {"current_version": 7}
        )

    @app.get("/test/not-found")
    async def not_found() -> None:
        raise AppError(ErrorCode.NOT_FOUND, "Проект не найден", 404)

    @app.post("/test/signup")
    async def signup(body: SignupBody) -> None:
        return None

    @app.get("/test/crash")
    async def crash() -> None:
        raise RuntimeError("секрет из исключения")

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # raise_app_exceptions=False: Starlette пробрасывает исключение после ответа 500,
    # а нам нужен сам ответ, который получит клиент.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_app_error_uses_unified_format(client: AsyncClient) -> None:
    response = await client.get("/test/conflict")

    assert response.status_code == 412
    assert response.json() == {
        "error": {
            "code": "file_conflict",
            "message": "Файл изменён в другом месте",
            "details": {"current_version": 7},
        }
    }


async def test_app_error_without_details_has_empty_details(client: AsyncClient) -> None:
    response = await client.get("/test/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Проект не найден", "details": {}}
    }


async def test_validation_error_lists_fields_in_russian(client: AsyncClient) -> None:
    response = await client.post("/test/signup", json={"password": "short", "age": "много"})

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "Проверьте введённые данные",
            "details": {
                "errors": [
                    {"loc": ["body", "email"], "type": "missing", "message": "Обязательное поле"},
                    {
                        "loc": ["body", "password"],
                        "type": "string_too_short",
                        "message": "Минимальная длина — 8",
                    },
                    {
                        "loc": ["body", "age"],
                        "type": "int_parsing",
                        "message": "Ожидается целое число",
                    },
                ]
            },
        }
    }


async def test_validation_error_does_not_echo_input(client: AsyncClient) -> None:
    response = await client.post(
        "/test/signup", json={"email": "a@b.ru", "password": "Pa$$w0r", "age": 1}
    )

    assert response.status_code == 422
    assert "Pa$$w0r" not in response.text


async def test_invalid_json_is_validation_error(client: AsyncClient) -> None:
    response = await client.post(
        "/test/signup", content=b"{", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["errors"][0]["type"] == "json_invalid"


async def test_unknown_path_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/no-such-endpoint")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Не найдено", "details": {}}
    }


async def test_wrong_method_is_method_not_allowed(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["Allow"] == "GET"


async def test_unhandled_exception_is_internal_and_logged(client: AsyncClient) -> None:
    with capture_logs() as logs:
        response = await client.get("/test/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal", "message": "Внутренняя ошибка сервера", "details": {}}
    }
    assert "секрет" not in response.text
    assert {
        "event": "unhandled_error",
        "log_level": "error",
        "method": "GET",
        "path": "/test/crash",
        "error_type": "RuntimeError",
    } in logs
