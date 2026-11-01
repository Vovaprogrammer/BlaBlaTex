"""Компилятор для тестов на httpx.MockTransport: отвечает по контракту 9.7 без сети и Docker."""

import email.parser
import email.policy
import io
import json
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from app.modules.builds.compiler import CompilerClient

PDF = b"%PDF-1.7 fake"
LOG = b"This is XeTeX, Version 3.141592653\nOutput written on out/main.xdv (1 page, 1234 bytes).\n"
SYNCTEX = b"fake synctex"
VERSION = "2025.1+0123456789abcdef"


def result_tar(result: dict[str, str | int | None] | None, files: dict[str, bytes]) -> bytes:
    """tar.gz ответа POST /compile: result.json (если result не None) и файлы сборки."""
    if result is not None:
        files = {"result.json": json.dumps(result).encode(), **files}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def ok_result(duration_ms: int = 1500) -> dict[str, str | int | None]:
    return {"status": "ok", "exit_code": 0, "duration_ms": duration_ms}


@dataclass(frozen=True)
class CompileRequest:
    """Что бэкенд прислал в POST /compile: поля формы и содержимое архива."""

    fields: dict[str, str]
    archive: bytes

    def files(self) -> dict[str, bytes]:
        """Файлы из архива: путь → содержимое."""
        with tarfile.open(fileobj=io.BytesIO(self.archive), mode="r:gz") as tar:
            return {
                member.name: tar.extractfile(member).read()  # type: ignore[union-attr]
                for member in tar
                if member.isfile()
            }


def parse_compile_request(request: httpx.Request) -> CompileRequest:
    """Разбирает multipart запроса стандартным парсером почты: формат тот же."""
    body = request.read()
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + body)
    fields: dict[str, str] = {}
    archive = b""
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        assert isinstance(name, str) and isinstance(payload, bytes)
        if name == "archive":
            archive = payload
        else:
            fields[name] = payload.decode()
    return CompileRequest(fields, archive)


@dataclass
class FakeCompiler:
    """Отвечает на /health версией, на /compile — заданным результатом.

    result и files — что вернёт следующая сборка; respond — свой ответ вместо них;
    error — исключение транспорта (компилятор недоступен); version=None — /health без версии.
    """

    version: str | None = VERSION
    result: dict[str, str | int | None] = field(default_factory=ok_result)
    files: dict[str, bytes] = field(
        default_factory=lambda: {"output.pdf": PDF, "output.log": LOG, "output.synctex.gz": SYNCTEX}
    )
    respond: Callable[[httpx.Request], httpx.Response] | None = None
    error: Exception | None = None
    requests: list[CompileRequest] = field(default_factory=list)
    timeouts: list[dict[str, float | None]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.error is not None:
            raise self.error
        if request.url.path == "/health":
            health = (
                {"status": "ok"}
                if self.version is None
                else {"status": "ok", "version": self.version}
            )
            return httpx.Response(200, json=health)
        assert (request.method, request.url.path) == ("POST", "/compile")
        self.timeouts.append(request.extensions["timeout"])
        self.requests.append(parse_compile_request(request))
        if self.respond is not None:
            return self.respond(request)
        return httpx.Response(
            200,
            content=result_tar(self.result, self.files),
            headers={"content-type": "application/gzip"},
        )

    def client(self) -> CompilerClient:
        transport = httpx.MockTransport(self.handle)
        return CompilerClient(httpx.AsyncClient(transport=transport, base_url="http://compiler"))
