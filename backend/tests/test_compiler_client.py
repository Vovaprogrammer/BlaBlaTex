"""Клиент компилятора против подмены на httpx.MockTransport: запросы и ответы по 9.7."""

import asyncio

import httpx
import pytest

from app.modules.builds.compiler import (
    BUILD_TIMEOUT_S,
    MAX_PARALLEL_COMPILES,
    QUEUE_WAIT_S,
    SYNCTEX_TIMEOUT,
    TRANSFER_MARGIN_S,
    CompilerError,
    CompilerRejectedError,
    CompilerUnavailableError,
    parse_result,
)
from app.modules.builds.schemas import SyncTexBox, SyncTexSource
from tests.fake_compiler import (
    LOG,
    PDF,
    SYNCTEX,
    VERSION,
    FakeCompiler,
    SyncTexRequest,
    ok_result,
    result_tar,
)

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
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.WriteTimeout("queued"),
        # Например, прокси перед компилятором испортил Content-Encoding.
        httpx.DecodingError("bad gzip"),
    ],
    ids=["not-running", "read-timeout", "write-timeout", "decoding"],
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


async def test_client_sends_at_most_two_builds_at_once(fake: FakeCompiler) -> None:
    # Компилятор собирает не больше двух проектов сразу (9.7), лишние ждут у клиента.
    two_compiling, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        if len(fake.requests) == MAX_PARALLEL_COMPILES:
            two_compiling.set()
        await release.wait()
        return fake.build_response()

    fake.respond = respond
    client = fake.client()
    builds = [
        asyncio.create_task(client.compile(ARCHIVE, main="main.tex", engine="xelatex"))
        for _ in range(MAX_PARALLEL_COMPILES + 1)
    ]
    await asyncio.wait_for(two_compiling.wait(), timeout=5)
    await asyncio.sleep(0.05)
    sent_while_busy = len(fake.requests)
    release.set()
    await asyncio.gather(*builds)

    assert MAX_PARALLEL_COMPILES == 2
    assert sent_while_busy == 2
    assert len(fake.requests) == 3


async def test_synctex_queries_send_file_and_fields(fake: FakeCompiler) -> None:
    box = {"page": 2, "x": 85.04, "y": 121.08, "width": 481.89, "height": 12.49}
    fake.synctex_answers = {
        "edit": {"source": {"path": "sections/goal.tex", "line": 2}},
        "view": {"boxes": [box]},
    }
    client = fake.client()

    edit = await client.synctex_edit(SYNCTEX, page=2, x=300, y=128.5)
    view = await client.synctex_view(SYNCTEX, path="sections/goal.tex", line=2)

    assert edit.source == SyncTexSource(path="sections/goal.tex", line=2)
    assert view.boxes == [SyncTexBox(**box)]
    assert fake.synctex_requests == [
        SyncTexRequest("edit", {"page": "2", "x": "300", "y": "128.5"}, SYNCTEX),
        SyncTexRequest("view", {"path": "sections/goal.tex", "line": "2"}, SYNCTEX),
    ]
    # Ждать долго незачем: synctex отвечает за секунды, у него своя очередь в компиляторе.
    assert fake.timeouts == [SYNCTEX_TIMEOUT.as_dict()] * 2


async def test_synctex_does_not_wait_for_build_slots(fake: FakeCompiler) -> None:
    compiling, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        if len(fake.requests) == MAX_PARALLEL_COMPILES:
            compiling.set()
        await release.wait()
        return fake.build_response()

    fake.respond = respond
    client = fake.client()
    builds = [
        asyncio.create_task(client.compile(ARCHIVE, main="main.tex", engine="xelatex"))
        for _ in range(MAX_PARALLEL_COMPILES)
    ]
    await asyncio.wait_for(compiling.wait(), timeout=5)

    answer = await asyncio.wait_for(client.synctex_edit(SYNCTEX, page=1, x=1, y=1), timeout=5)

    assert answer.source is None
    release.set()
    await asyncio.gather(*builds)


@pytest.mark.parametrize("status", [413, 422])
async def test_synctex_rejection(fake: FakeCompiler, status: int) -> None:
    fake.synctex_status = status
    fake.synctex_answers["view"] = {"error": {"code": "validation_error"}}

    with pytest.raises(CompilerRejectedError):
        await fake.client().synctex_view(SYNCTEX, path="main.tex", line=1)
