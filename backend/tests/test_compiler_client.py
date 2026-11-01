"""Клиент компилятора против подмены на httpx.MockTransport: запросы и ответы по 9.7."""

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.modules.builds.compiler import (
    BUILD_TIMEOUT_S,
    QUEUE_WAIT_S,
    TRANSFER_MARGIN_S,
    CompilerError,
    CompilerRejectedError,
    CompilerUnavailableError,
    parse_result,
)
from tests.fake_compiler import LOG, PDF, SYNCTEX, VERSION, FakeCompiler, ok_result, result_tar

ARCHIVE = b"fake tar.gz"


@pytest.fixture
def fake() -> FakeCompiler:
    return FakeCompiler()


async def test_version_comes_from_health(fake: FakeCompiler) -> None:
    assert await fake.client().version() == VERSION


async def test_health_without_version_is_compiler_error(fake: FakeCompiler) -> None:
    # Например, бэкенд обновили, а компилятор — ещё нет.
    fake.version = None

    with pytest.raises(CompilerError):
        await fake.client().version()


async def test_compile_sends_archive_and_fields(fake: FakeCompiler) -> None:
    await fake.client().compile(ARCHIVE, main="report/lab.tex", engine="pdflatex", timeout_s=30)

    [request] = fake.requests
    assert request.archive == ARCHIVE
    assert request.fields == {"main": "report/lab.tex", "engine": "pdflatex", "timeout_s": "30"}


async def test_compile_timeout_covers_queue_and_build(fake: FakeCompiler) -> None:
    await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")

    # Запрос может ждать очереди, не отправив тело: таймаут и на чтение, и на запись.
    expected = BUILD_TIMEOUT_S + QUEUE_WAIT_S + TRANSFER_MARGIN_S
    assert fake.timeouts[0]["read"] == expected
    assert fake.timeouts[0]["write"] == expected
    assert fake.requests[0].fields["timeout_s"] == str(BUILD_TIMEOUT_S)


async def test_successful_build_returns_all_files(fake: FakeCompiler) -> None:
    result = await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")

    assert (result.status, result.exit_code, result.duration_ms) == ("ok", 0, 1500)
    assert (result.pdf, result.log, result.synctex) == (PDF, LOG, SYNCTEX)


async def test_latex_error_is_result_without_pdf(fake: FakeCompiler) -> None:
    fake.result = {"status": "error", "exit_code": 12, "duration_ms": 900}
    fake.files = {"output.log": LOG}

    result = await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")

    assert (result.status, result.exit_code) == ("error", 12)
    assert (result.pdf, result.synctex, result.log) == (None, None, LOG)


async def test_timeout_has_no_exit_code(fake: FakeCompiler) -> None:
    fake.result = {"status": "timeout", "exit_code": None, "duration_ms": 60_000}
    fake.files = {"output.log": b"latexmk output"}

    result = await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")

    assert (result.status, result.exit_code) == ("timeout", None)


async def test_validation_error_is_rejected_with_code_and_loc(fake: FakeCompiler) -> None:
    body = {
        "error": {
            "code": "validation_error",
            "message": "Неверный запрос на сборку",
            "details": {
                "errors": [
                    {"loc": ["body", "archive"], "type": "reserved_path", "message": "Папка out/"}
                ]
            },
        }
    }
    fake.respond = lambda request: httpx.Response(422, json=body)

    with pytest.raises(CompilerRejectedError) as error:
        await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")

    assert (error.value.status, error.value.code) == (422, "validation_error")
    assert error.value.locs == [["body", "archive"]]


async def test_payload_too_large_is_rejected(fake: FakeCompiler) -> None:
    body = {"error": {"code": "payload_too_large", "message": "Архив слишком большой"}}
    fake.respond = lambda request: httpx.Response(413, json=body)

    with pytest.raises(CompilerRejectedError) as error:
        await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")

    assert (error.value.status, error.value.code, error.value.locs) == (
        413,
        "payload_too_large",
        [],
    )


async def test_rejection_without_json_body_is_still_rejected(fake: FakeCompiler) -> None:
    fake.respond = lambda request: httpx.Response(413, text="Request Entity Too Large")

    with pytest.raises(CompilerRejectedError) as error:
        await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")

    assert (error.value.status, error.value.code) == (413, "unknown")


async def test_server_error_means_unavailable(fake: FakeCompiler) -> None:
    fake.respond = lambda request: httpx.Response(500, json={"error": {"code": "internal"}})

    with pytest.raises(CompilerUnavailableError):
        await fake.client().compile(ARCHIVE, main="main.tex", engine="xelatex")


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.WriteTimeout("queued")],
    ids=["not-running", "read-timeout", "write-timeout"],
)
async def test_transport_errors_mean_unavailable(fake: FakeCompiler, error: Exception) -> None:
    fake.error = error
    client = fake.client()

    with pytest.raises(CompilerUnavailableError):
        await client.version()
    with pytest.raises(CompilerUnavailableError):
        await client.compile(ARCHIVE, main="main.tex", engine="xelatex")


@pytest.mark.parametrize(
    "body",
    [
        b"not a tar.gz",
        result_tar({"status": "ok", "exit_code": 0, "duration_ms": 1}, {})[:-20],
        result_tar({"status": "done", "exit_code": 0, "duration_ms": 1}, {}),
        result_tar({"status": "ok"}, {}),
        result_tar(None, {"output.pdf": PDF, "output.log": LOG}),
    ],
    ids=["garbage", "truncated", "unknown-status", "missing-fields", "no-result-json"],
)
def test_broken_response_is_compiler_error(body: bytes) -> None:
    with pytest.raises(CompilerError):
        parse_result(body)


def test_unknown_files_in_response_are_ignored() -> None:
    body = result_tar(ok_result(), {"output.pdf": PDF, "output.log": LOG, "extra.bin": b"x"})

    result = parse_result(body)

    assert (result.pdf, result.log, result.synctex) == (PDF, LOG, None)


async def test_lifespan_creates_client_for_settings_url(app: FastAPI, settings: Settings) -> None:
    async with app.router.lifespan_context(app):
        http = app.state.compiler.http

        assert str(http.base_url) == f"http://localhost:{settings.compiler_port}"
        assert not http.is_closed

    assert http.is_closed
