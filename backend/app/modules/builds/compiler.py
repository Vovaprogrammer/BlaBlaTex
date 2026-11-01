"""Клиент сервиса компиляции (architecture.md 9.7): tar.gz проекта туда, результат сборки обратно.

Компилятор ничего не знает о проектах и базе — только об архиве, главном файле и движке.
"""

import asyncio
import gzip
import io
import tarfile
import zlib
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.modules.projects.schemas import Engine

CompileStatus = Literal["ok", "error", "timeout"]

# Сборка — до 60 с (9.8).
BUILD_TIMEOUT_S = 60
# Компилятор собирает не больше двух проектов сразу, остальные запросы ждут очереди (9.7).
QUEUE_WAIT_S = 120
# Передача архива, распаковка и упаковка результата.
TRANSFER_MARGIN_S = 30
# /health и подключение отвечают сразу — долго ждать нечего.
CONNECT_TIMEOUT_S = 10

_RESULT_FILES = ("output.pdf", "output.log", "output.synctex.gz")


class CompilerError(Exception):
    """Компилятор ответил не по контракту 9.7."""


class CompilerUnavailableError(CompilerError):
    """Компилятор не ответил: не запущен, перегружен или упал (5xx)."""


class CompilerRejectedError(CompilerError):
    """Компилятор отклонил запрос (422 или 413).

    Бэкенд заранее проверяет то же самое, поэтому такой ответ — ошибка в бэкенде, а не
    у пользователя. code и loc — из ответа 9.2, без текста: в нём бывают пути из проекта.
    """

    def __init__(self, status: int, code: str, locs: list[list[str | int]]) -> None:
        super().__init__(f"Компилятор отклонил запрос: {status} {code}")
        self.status = status
        self.code = code
        self.locs = locs


@dataclass(frozen=True)
class CompileResult:
    """Ответ компилятора: итог из result.json и файлы, которые он вернул."""

    status: CompileStatus
    # При таймауте — None.
    exit_code: int | None
    duration_ms: int
    pdf: bytes | None
    log: bytes
    synctex: bytes | None


class _ResultJson(BaseModel):
    status: CompileStatus
    exit_code: int | None
    duration_ms: int


class _Health(BaseModel):
    version: str


# Ответ 9.2 компилятора: из него нужны только код и места ошибок по полям.
class _RejectedField(BaseModel):
    loc: list[str | int]


class _RejectedDetails(BaseModel):
    errors: list[_RejectedField] = []


class _RejectedError(BaseModel):
    code: str
    details: _RejectedDetails = Field(default_factory=_RejectedDetails)


class _Rejected(BaseModel):
    error: _RejectedError


def compile_timeout(timeout_s: int) -> httpx.Timeout:
    """Таймауты запроса на сборку: сама сборка, очередь и передача.

    Не только чтение, но и запись: пока запрос ждёт очереди, компилятор не читает его тело,
    и большой архив не уходит целиком.
    """
    wait = timeout_s + QUEUE_WAIT_S + TRANSFER_MARGIN_S
    return httpx.Timeout(connect=CONNECT_TIMEOUT_S, read=wait, write=wait, pool=CONNECT_TIMEOUT_S)


def create_http_client(base_url: str) -> httpx.AsyncClient:
    """HTTP-клиент к компилятору. Один на приложение: соединения переиспользуются."""
    return httpx.AsyncClient(base_url=base_url, timeout=CONNECT_TIMEOUT_S)


class CompilerClient:
    """Запросы к компилятору. Любой сбой связи или ответ не по контракту — CompilerError."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def version(self) -> str:
        """Версия сборочного окружения из GET /health — часть ключа кэша сборок."""
        response = await self._send(self.http.build_request("GET", "/health"))
        if response.status_code != 200:
            raise CompilerUnavailableError(f"/health ответил {response.status_code}")
        try:
            return _Health.model_validate_json(response.content).version
        except ValidationError as error:
            raise CompilerError("/health ответил без version") from error

    async def compile(
        self,
        archive: bytes,
        *,
        main: str,
        engine: Engine,
        timeout_s: int = BUILD_TIMEOUT_S,
    ) -> CompileResult:
        """Собирает проект из tar.gz. Ошибка LaTeX и таймаут — это результат, а не исключение."""
        request = self.http.build_request(
            "POST",
            "/compile",
            files={"archive": ("project.tar.gz", archive, "application/gzip")},
            data={"main": main, "engine": engine, "timeout_s": str(timeout_s)},
            timeout=compile_timeout(timeout_s),
        )
        response = await self._send(request)
        if response.status_code in (413, 422):
            raise _rejected(response)
        if response.status_code != 200:
            raise CompilerUnavailableError(f"/compile ответил {response.status_code}")
        # Распаковка ответа — работа процессора, вместе с PDF это десятки МБ.
        return await asyncio.to_thread(parse_result, response.content)

    async def _send(self, request: httpx.Request) -> httpx.Response:
        try:
            return await self.http.send(request)
        except httpx.RequestError as error:
            # Не запущен, обрыв связи, истёк таймаут или ответ не раскодировать.
            raise CompilerUnavailableError(type(error).__name__) from error


def _rejected(response: httpx.Response) -> CompilerRejectedError:
    try:
        error = _Rejected.model_validate_json(response.content).error
    except ValidationError:
        return CompilerRejectedError(response.status_code, "unknown", [])
    locs = [field.loc for field in error.details.errors]
    return CompilerRejectedError(response.status_code, error.code, locs)


def parse_result(data: bytes) -> CompileResult:
    """Разбирает tar.gz ответа: result.json и файлы сборки. Лишние файлы не читаются."""
    try:
        # gzip распаковывается целиком: так обрезанный ответ не сойдёт за целый —
        # tarfile сам по себе не замечает потерю хвоста архива.
        raw = gzip.decompress(data)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
            files: dict[str, bytes] = {}
            for member in tar:
                if member.isfile() and member.name in ("result.json", *_RESULT_FILES):
                    content = tar.extractfile(member)
                    if content is not None:
                        files[member.name] = content.read()
        result = _ResultJson.model_validate_json(files["result.json"])
    # OSError — в том числе gzip.BadGzipFile.
    except (tarfile.TarError, EOFError, OSError, zlib.error, KeyError, ValidationError) as error:
        raise CompilerError("Ответ компилятора не разобрать") from error
    return CompileResult(
        status=result.status,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        pdf=files.get("output.pdf"),
        log=files.get("output.log", b""),
        synctex=files.get("output.synctex.gz"),
    )
