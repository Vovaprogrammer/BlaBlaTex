"""Сценарии eval с синтетическими кейсами и MockTransport вместо реального API."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from eval.runner import CaseError, load_case, local_url, run_case, wait_run

PROJECT = "a0000000-0000-4000-8000-000000000001"
RUN = "a0000000-0000-4000-8000-000000000002"
MESSAGE = "a0000000-0000-4000-8000-000000000003"
BUILD = "a0000000-0000-4000-8000-000000000004"


@pytest.fixture
def case(tmp_path: Path) -> Path:
    folder = tmp_path / "demo-01"
    (folder / "materials" / "code").mkdir(parents=True)
    (folder / "case.yaml").write_text(
        "id: demo-01\nmeta:\n  lab_number: 1\nexpected:\n  sections: [Цель, Выводы, Нет]\n",
        encoding="utf-8",
    )
    (folder / "materials" / "task.txt").write_text("задание", encoding="utf-8")
    (folder / "materials" / "code" / "main.py").write_text("x = 1\n", encoding="utf-8")
    return folder


def handler(events: bool = True, run_status: str = "done"):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path.removeprefix("/api/v1")
        if path == "/projects" and request.method == "POST":
            return httpx.Response(201, json={"id": PROJECT})
        if path == f"/projects/{PROJECT}/upload":
            return httpx.Response(200, json={"items": []})
        if path == f"/projects/{PROJECT}/messages" and request.method == "POST":
            return httpx.Response(201, json={"run": {"id": RUN, "message_id": MESSAGE}})
        if path == f"/projects/{PROJECT}/events":
            if not events:
                return httpx.Response(200, text="")
            data = {
                "run_id": RUN,
                "status": run_status,
                "usage": {"tokens_in": 23, "tokens_out": 7},
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"id: 1-0\nevent: run.finished\ndata: {json.dumps(data)}\n\n",
            )
        if path == f"/projects/{PROJECT}/messages":
            return httpx.Response(200, json={"items": [{"id": MESSAGE, "status": run_status}]})
        if path == f"/projects/{PROJECT}/template-guide":
            return httpx.Response(
                200,
                json={
                    "sections": [
                        {"title": "Цель", "file": "sections/goal.tex"},
                        {"title": "Выводы", "file": "sections/end.tex"},
                    ]
                },
            )
        if path == f"/projects/{PROJECT}/tree":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"path": "sections/goal.tex", "kind": "text"},
                    ]
                },
            )
        if path == f"/projects/{PROJECT}/builds":
            return httpx.Response(202, json={"id": BUILD, "status": "queued"})
        if path == f"/builds/{BUILD}":
            return httpx.Response(200, json={"id": BUILD, "status": "ok", "has_pdf": True})
        if path == f"/builds/{BUILD}/pdf":
            return httpx.Response(200, content=b"%PDF-synthetic")
        raise AssertionError(f"Unexpected endpoint: {request.method} {path}")

    return respond, requests


@pytest.mark.asyncio
async def test_complete_case_uploads_nested_and_reads_finished_event(case: Path, tmp_path: Path):
    respond, requests = handler()
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8765/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        result = await run_case(client, case, tmp_path / "results", timeout_s=3)
    assert result["error"] is None
    assert result["run_status"] == "done"
    assert result["build_status"] == "ok"
    assert result["pdf_downloaded"] is True
    assert (tmp_path / "results" / "demo-01.pdf").read_bytes() == b"%PDF-synthetic"
    assert (result["tokens_in"], result["tokens_out"]) == (23, 7)
    assert result["cost"] is None and result["compile_calls"] is None
    assert result["section_files"] == {"Цель": True, "Выводы": False, "Нет": None}
    uploads = [r for r in requests if r.url.path.endswith("/upload")]
    assert len(uploads) == 2
    assert any(b"materials/code" in r.content for r in uploads)
    assert any(b'filename="main.py"' in r.content for r in uploads)
    event_request = next(r for r in requests if r.url.path.endswith("/events"))
    assert event_request.headers["Last-Event-ID"] == "0-0"
    wait_request = next(r for r in requests if r.url.path == f"/api/v1/builds/{BUILD}")
    assert wait_request.url.params["wait"] == "60"


@pytest.mark.asyncio
async def test_missing_event_uses_terminal_message_without_fabricating_usage(
    case: Path, tmp_path: Path
):
    respond, _ = handler(events=False)
    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        result = await run_case(client, case, tmp_path / "results", timeout_s=3)
    assert result["run_status"] == "done"
    assert result["tokens_in"] is result["tokens_out"] is None
    assert result["compile_calls"] is result["cost"] is None


@pytest.mark.asyncio
async def test_failed_run_does_not_start_build(case: Path, tmp_path: Path):
    respond, requests = handler(run_status="failed")
    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        result = await run_case(client, case, tmp_path / "results", timeout_s=3)
    assert result["run_status"] == "failed" and result["error"] == "run_not_done"
    assert not any(r.url.path.endswith("/builds") for r in requests)


@pytest.mark.asyncio
async def test_http_error_does_not_leak_response(case: Path, tmp_path: Path):
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="secret test material")

    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        result = await run_case(client, case, tmp_path / "results")
    assert result["error"] == "http_status"
    assert "secret test material" not in json.dumps(result)


def test_rejects_material_symlink_and_hidden_names(case: Path, tmp_path: Path):
    (case / "materials" / "link.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(CaseError, match="invalid_material"):
        load_case(case)
    (case / "materials" / "link.txt").unlink()
    (case / "materials" / ".env").write_text("synthetic", encoding="utf-8")
    with pytest.raises(CaseError, match="invalid_material"):
        load_case(case)
    (case / "materials" / ".env").unlink()
    (case / "materials" / "key.pem").write_text("synthetic", encoding="utf-8")
    with pytest.raises(CaseError, match="invalid_material"):
        load_case(case)


def test_rejects_case_id_mismatch_and_symlink_folder(case: Path, tmp_path: Path):
    link = tmp_path / "alias"
    link.symlink_to(case, target_is_directory=True)
    with pytest.raises(CaseError, match="invalid_case"):
        load_case(link)
    (case / "case.yaml").write_text("id: ../outside\nmeta: {}\n", encoding="utf-8")
    with pytest.raises(CaseError, match="invalid_case"):
        load_case(case)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/api/v1",
        "https://evil.example/api",
        "http://user:key@localhost/api",
        "http://localhost/api?token=x",
    ],
)
def test_external_or_credential_urls_rejected(url: str):
    with pytest.raises(ValueError):
        local_url(url)


def test_loopback_url_allowed():
    assert local_url("http://127.0.0.1:8765/api/v1/") == "http://127.0.0.1:8765/api/v1"


@pytest.mark.asyncio
async def test_wait_run_deadline_and_missing_event_do_not_hang(case: Path, tmp_path: Path):
    respond, _ = handler(events=False, run_status="running")
    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        result = await run_case(client, case, tmp_path / "out", timeout_s=0.05)
    assert result["error"] == "run_timeout"
    assert result["tokens_in"] is result["tokens_out"] is None


@pytest.mark.asyncio
async def test_pdf_error_is_not_counted_as_download(case: Path, tmp_path: Path):
    respond, _ = handler()

    def with_invalid_pdf(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pdf"):
            return httpx.Response(200, content=b"not pdf")
        return respond(request)

    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(with_invalid_pdf)
    ) as client:
        result = await run_case(client, case, tmp_path / "out", timeout_s=3)
    assert result["error"] == "invalid_pdf"
    assert result["pdf_downloaded"] is False
    assert not (tmp_path / "out" / "demo-01.pdf").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "has_pdf", "expected"),
    [
        ("ok", False, "pdf_missing"),
        ("error", False, "build_failed"),
        ("timeout", False, "build_timeout"),
    ],
)
async def test_missing_pdf_and_failed_builds_are_errors(
    case: Path, tmp_path: Path, status: str, has_pdf: bool, expected: str
):
    respond, requests = handler()

    def with_build(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/builds/{BUILD}":
            return httpx.Response(200, json={"id": BUILD, "status": status, "has_pdf": has_pdf})
        return respond(request)

    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(with_build)
    ) as client:
        result = await run_case(client, case, tmp_path / "out", timeout_s=3)
    assert result["build_status"] == status
    assert result["error"] == expected and result["pdf_downloaded"] is False
    assert not any(r.url.path.endswith("/pdf") for r in requests)


@pytest.mark.asyncio
async def test_invalid_id_does_not_issue_followup_request(case: Path, tmp_path: Path):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "../../other"})

    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        result = await run_case(client, case, tmp_path / "out")
    assert result["error"] == "invalid_response"
    assert len(requests) == 1


def test_cli_against_loopback_http(case: Path, tmp_path: Path):
    respond, _ = handler()
    data_dir = tmp_path / "input"
    data_dir.mkdir()
    case.rename(data_dir / case.name)

    class Server(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def serve(self) -> None:
            assert self.headers.get("Authorization") == "Bearer synthetic-test-token"
            content = self.rfile.read(int(self.headers.get("content-length", "0")))
            request = httpx.Request(self.command, f"http://localhost{self.path}", content=content)
            response = respond(request)
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = serve
        do_POST = serve

    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {"BLABLATEX_TOKEN": "synthetic-test-token"}
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.runner",
                "--data-dir",
                str(data_dir),
                "--output-dir",
                str(tmp_path / "output"),
                "--url",
                f"http://127.0.0.1:{server.server_port}/api/v1",
                "--timeout",
                "5",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        assert process.returncode == 0, process.stderr
        result = json.loads((tmp_path / "output" / "demo-01.json").read_text())
        assert result["run_status"] == "done" and result["pdf_downloaded"] is True
        assert result["tokens_in"] == 23 and result["tokens_out"] == 7
        assert (tmp_path / "output" / "demo-01.pdf").read_bytes() == b"%PDF-synthetic"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def full_run_events() -> list[str]:
    return [
        sse("run.started", {"run_id": RUN, "message_id": MESSAGE}),
        sse("run.tool_call", {"run_id": RUN, "seq": 1, "tool": "compile"}),
        sse("run.tool_result", {"run_id": RUN, "seq": 2}),
        sse("run.delta", {"run_id": RUN, "seq": 3}),
        sse("run.tool_call", {"run_id": RUN, "seq": 4, "tool": "read_file"}),
        sse("run.tool_result", {"run_id": RUN, "seq": 5}),
        sse(
            "run.finished",
            {"run_id": RUN, "status": "done", "usage": {"tokens_in": 23, "tokens_out": 7}},
        ),
    ]


@pytest.mark.asyncio
async def test_compile_count_requires_full_sse_and_matching_final_seq():
    events = full_run_events()
    # Чужой прогон не влияет на счётчик и последовательность.
    events.insert(2, sse("run.tool_call", {"run_id": PROJECT, "seq": 1, "tool": "compile"}))

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return httpx.Response(200, text="".join(events))
        return httpx.Response(200, json={"items": [{"id": MESSAGE, "status": "done", "seq": 5}]})

    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        assert await wait_run(client, PROJECT, RUN, MESSAGE, 3) == ("done", 23, 7, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem",
    [
        "missing_start",
        "gap",
        "duplicate",
        "missing_finish",
        "wrong_final_seq",
        "missing_message",
        "disconnected",
    ],
)
async def test_compile_count_is_unknown_for_incomplete_evidence(problem: str):
    events = full_run_events()
    message = {"id": MESSAGE, "status": "done", "seq": 5}
    if problem == "missing_start":
        events.pop(0)
    elif problem == "gap":
        events.pop(2)
    elif problem == "duplicate":
        events.insert(2, events[1])
    elif problem == "missing_finish":
        events.pop()
    elif problem == "wrong_final_seq":
        message["seq"] = 6

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return (
                httpx.Response(503)
                if problem == "disconnected"
                else httpx.Response(200, text="".join(events))
            )
        return httpx.Response(
            200, json={"items": [] if problem == "missing_message" else [message]}
        )

    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        status, tokens_in, tokens_out, count = await wait_run(client, PROJECT, RUN, MESSAGE, 0.2)
    assert status == "done"
    assert count is None
    if problem not in ("missing_finish", "disconnected"):
        assert (tokens_in, tokens_out) == (23, 7)


@pytest.mark.asyncio
async def test_complete_no_tool_events_reports_zero_calls():
    events = [full_run_events()[0], full_run_events()[-1]]

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return httpx.Response(200, text="".join(events))
        return httpx.Response(200, json={"items": [{"id": MESSAGE, "status": "done", "seq": 0}]})

    async with httpx.AsyncClient(
        base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        assert await wait_run(client, PROJECT, RUN, MESSAGE, 3) == ("done", 23, 7, 0)
