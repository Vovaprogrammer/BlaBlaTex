"""Единый формат ошибок API (architecture.md 9.2): AppError, схемы ответа и обработчики."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, JsonValue
from pydantic_core import ErrorDetails
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class ErrorCode(StrEnum):
    """Коды ошибок из таблицы architecture.md 9.2."""

    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    ALREADY_EXISTS = "already_exists"
    FILE_CONFLICT = "file_conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    PROJECT_LOCKED = "project_locked"
    QUOTA_EXCEEDED = "quota_exceeded"
    RATE_LIMITED = "rate_limited"
    INTERNAL = "internal"
    NOT_IMPLEMENTED = "not_implemented"


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str = Field(description="Текст для пользователя, на русском")
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Тело любого ответа с ошибкой."""

    error: ErrorBody


class FieldError(BaseModel):
    loc: list[str | int] = Field(description="Где ошибка: body, query, path или header и имя поля")
    type: str = Field(description="Тип ошибки Pydantic, например missing")
    message: str


class ValidationErrorDetails(BaseModel):
    errors: list[FieldError]


class ValidationErrorBody(BaseModel):
    code: Literal[ErrorCode.VALIDATION_ERROR] = ErrorCode.VALIDATION_ERROR
    message: str
    details: ValidationErrorDetails


class ValidationErrorResponse(BaseModel):
    """Ответ 422: ErrorResponse, у которого в details — ошибки по полям."""

    error: ValidationErrorBody


class AppError(Exception):
    """Ошибка для пользователя: код из 9.2, текст на русском и HTTP-статус."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status: int,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


VALIDATION_MESSAGE = "Проверьте введённые данные"
INTERNAL_MESSAGE = "Внутренняя ошибка сервера"

# Ошибки, которые FastAPI и Starlette бросают сами: неизвестный адрес, не тот метод, кривое тело.
_HTTP_ERRORS: dict[int, tuple[ErrorCode, str]] = {
    400: (ErrorCode.VALIDATION_ERROR, "Не удалось разобрать запрос"),
    401: (ErrorCode.UNAUTHORIZED, "Нужно войти в аккаунт"),
    403: (ErrorCode.FORBIDDEN, "Нет доступа"),
    404: (ErrorCode.NOT_FOUND, "Не найдено"),
    405: (ErrorCode.METHOD_NOT_ALLOWED, "Этот метод здесь не поддерживается"),
    413: (ErrorCode.PAYLOAD_TOO_LARGE, "Слишком большой запрос"),
    415: (ErrorCode.UNSUPPORTED_FILE_TYPE, "Неподдерживаемый тип данных"),
}

# Русские тексты для частых ошибок Pydantic; в скобках — значения из ctx ошибки.
_FIELD_MESSAGES: dict[str, str] = {
    "missing": "Обязательное поле",
    "string_type": "Ожидается строка",
    "string_too_short": "Минимальная длина — {min_length}",
    "string_too_long": "Максимальная длина — {max_length}",
    "int_type": "Ожидается целое число",
    "int_parsing": "Ожидается целое число",
    "bool_type": "Ожидается true или false",
    "bool_parsing": "Ожидается true или false",
    "greater_than_equal": "Значение должно быть не меньше {ge}",
    "less_than_equal": "Значение должно быть не больше {le}",
    "literal_error": "Недопустимое значение",
    "enum": "Недопустимое значение",
    "uuid_type": "Некорректный идентификатор",
    "uuid_parsing": "Некорректный идентификатор",
    "dict_type": "Ожидается объект",
    "model_attributes_type": "Ожидается объект",
    "list_type": "Ожидается список",
    "json_invalid": "Некорректный JSON",
}
_DEFAULT_FIELD_MESSAGE = "Некорректное значение"


def _error_json(
    status: int,
    body: BaseModel,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(body.model_dump(mode="json"), status_code=status, headers=headers)


def _field_message(error: ErrorDetails) -> str:
    template = _FIELD_MESSAGES.get(error["type"], _DEFAULT_FIELD_MESSAGE)
    try:
        return template.format(**error.get("ctx", {}))
    except KeyError:
        return _DEFAULT_FIELD_MESSAGE


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    body = ErrorBody(code=exc.code, message=exc.message, details=exc.details)
    return _error_json(exc.status, ErrorResponse(error=body))


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Введённое значение (input) в ответ не кладём: там может быть пароль.
    errors = [
        FieldError(loc=list(err["loc"]), type=err["type"], message=_field_message(err))
        for err in exc.errors()
    ]
    body = ValidationErrorBody(
        message=VALIDATION_MESSAGE, details=ValidationErrorDetails(errors=errors)
    )
    return _error_json(422, ValidationErrorResponse(error=body))


async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    default = (
        (ErrorCode.INTERNAL, INTERNAL_MESSAGE)
        if exc.status_code >= 500
        else (ErrorCode.VALIDATION_ERROR, "Некорректный запрос")
    )
    code, message = _HTTP_ERRORS.get(exc.status_code, default)
    body = ErrorBody(code=code, message=message)
    # Заголовки сохраняем: например, Allow у ответа 405.
    return _error_json(exc.status_code, ErrorResponse(error=body), exc.headers)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Трейсбек здесь не пишем: dict_tracebacks в structlog выводит локальные переменные,
    # а в них бывают пароли. Starlette после ответа пробрасывает исключение дальше,
    # и трейсбек без переменных печатает сервер (uvicorn).
    logger.error(
        "unhandled_error",
        method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    body = ErrorBody(code=ErrorCode.INTERNAL, message=INTERNAL_MESSAGE)
    return _error_json(500, ErrorResponse(error=body))


def register_error_handlers(app: FastAPI) -> None:
    """Подключает обработчики: любая ошибка API уходит клиенту в формате 9.2."""
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
