"""Ответы об ошибках в формате architecture.md 9.2.

Ошибка LaTeX — не HTTP-ошибка, а статус сборки в result.json.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.archive import ArchiveTooLargeError
from app.synctex import SyncTexFileError, SyncTexRunError, SyncTexTooLargeError

log = structlog.get_logger()

# Any в этом модуле — JSON ответа: в нём строки, числа, списки и вложенные объекты вперемешку.
JsonObject = dict[str, Any]

_HTTP_ERRORS = {
    404: ("not_found", "Нет такого адреса"),
    405: ("method_not_allowed", "Метод не поддерживается"),
    413: ("payload_too_large", "Архив слишком большой"),
}

_FIELD_MESSAGES = {
    "missing": "Обязательное поле",
    "literal_error": "Недопустимое значение",
    "int_parsing": "Нужно целое число",
    "greater_than_equal": "Слишком маленькое значение",
    "less_than_equal": "Слишком большое значение",
    "float_parsing": "Нужно число",
}


class RequestFieldError(Exception):
    """Поле прошло схему, но не подходит по смыслу: битый архив, main не из архива."""

    def __init__(self, field: str, error_type: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.error_type = error_type
        self.message = message


def error_response(
    status: int, code: str, message: str, details: JsonObject | None = None
) -> JSONResponse:
    error: JsonObject = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse({"error": error}, status_code=status)


def payload_too_large() -> JSONResponse:
    return error_response(413, *_HTTP_ERRORS[413])


def _validation_error(request: Request, errors: list[JsonObject]) -> JSONResponse:
    what = "SyncTeX" if request.url.path.startswith("/synctex/") else "на сборку"
    return error_response(422, "validation_error", f"Неверный запрос {what}", {"errors": errors})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def on_request_validation(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # Введённое значение в ответ не попадает (9.2), только место и тип ошибки.
        return _validation_error(
            request,
            [
                {
                    "loc": list(item["loc"]),
                    "type": item["type"],
                    "message": _FIELD_MESSAGES.get(item["type"], "Недопустимое значение"),
                }
                for item in error.errors()
            ],
        )

    @app.exception_handler(RequestFieldError)
    async def on_field_error(request: Request, error: RequestFieldError) -> JSONResponse:
        return _validation_error(
            request,
            [{"loc": ["body", error.field], "type": error.error_type, "message": error.message}],
        )

    @app.exception_handler(ArchiveTooLargeError)
    async def on_too_large(_: Request, error: ArchiveTooLargeError) -> JSONResponse:
        return error_response(413, "payload_too_large", str(error))

    @app.exception_handler(SyncTexFileError)
    async def on_bad_synctex(request: Request, error: SyncTexFileError) -> JSONResponse:
        return _validation_error(
            request,
            [{"loc": ["body", "synctex"], "type": "invalid_synctex", "message": str(error)}],
        )

    @app.exception_handler(SyncTexTooLargeError)
    async def on_synctex_too_large(_: Request, error: SyncTexTooLargeError) -> JSONResponse:
        return error_response(413, "payload_too_large", str(error))

    @app.exception_handler(SyncTexRunError)
    async def on_synctex_failed(_: Request, error: SyncTexRunError) -> JSONResponse:
        log.error("synctex_failed", reason=str(error))
        return error_response(500, "internal", "synctex не ответил")

    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, error: HTTPException) -> JSONResponse:
        if error.status_code == 400:
            # Так FastAPI сообщает, что не смог разобрать multipart.
            return _validation_error(
                request,
                [{"loc": ["body"], "type": "invalid_body", "message": "Тело запроса не разобрать"}],
            )
        code, message = _HTTP_ERRORS.get(error.status_code, ("internal", "Внутренняя ошибка"))
        return error_response(error.status_code, code, message)

    @app.exception_handler(Exception)
    async def on_unhandled(_: Request, error: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(error).__name__)
        return error_response(500, "internal", "Внутренняя ошибка компилятора")
