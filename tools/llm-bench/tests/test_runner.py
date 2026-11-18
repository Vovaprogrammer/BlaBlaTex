"""Проверки протокола бенчмарка на синтетическом HTTP API."""

import json
from pathlib import Path

import httpx

from llm_bench.config import Provider
from llm_bench.runner import BROKEN, FakeDocument, Usage, run_content_scenario, run_tool_scenario

PROVIDER = Provider(name="mock", base_url="https://example.invalid/v1", model="model")


def message_response(message: dict, *, usage: dict | None = None) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": message}], "usage": usage})


def tool_call(name: str, arguments: dict, index: int) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": str(index),
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def test_tool_scenario_executes_protocol_and_sums_usage() -> None:
    replies = iter(
        [
            tool_call("read_file", {"path": "main.tex"}, 1),
            tool_call(
                "edit_file", {"path": "main.tex", "old": "\\unknowncommand", "new": "world"}, 2
            ),
            tool_call("compile", {}, 3),
        ]
    )
    seen: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        seen.append(data)
        return message_response(
            next(replies),
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "prompt_tokens_details": {"cached_tokens": 3},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = run_tool_scenario(client, PROVIDER)
    assert result["success"] is True
    assert result["tools_called"] == {"read_file": True, "edit_file": True, "compile": True}
    assert result["final_compile_ok"] is True
    assert result["requests"] == 3
    assert (result["input_tokens"], result["output_tokens"], result["cached_input_tokens"]) == (
        30,
        6,
        9,
    )
    assert seen[1]["messages"][-1]["content"] == BROKEN
    assert seen[2]["messages"][-1]["content"] == "Файл изменён"


def test_compilation_must_follow_successful_edit() -> None:
    document = FakeDocument()
    assert document.call("compile", {}) != "Сборка успешна"
    assert (
        document.call("edit_file", {"path": "main.tex", "old": "\\unknowncommand", "new": "world"})
        == "Файл изменён"
    )
    assert not document.compiled
    assert document.call("compile", {}) == "Сборка успешна"
    document.call("edit_file", {"path": "main.tex", "old": "world", "new": "bad"})
    assert not document.compiled


def test_missing_usage_is_unknown_even_if_other_calls_report_it() -> None:
    usage = Usage()
    usage.add({"usage": {"prompt_tokens": 1, "completion_tokens": 2}})
    usage.add(
        {
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 4,
                "prompt_tokens_details": {"cached_tokens": 1},
            }
        }
    )
    assert usage.values == {"input_tokens": 4, "output_tokens": 6, "cached_input_tokens": None}


def test_section_and_vision_send_expected_inputs(tmp_path: Path) -> None:
    text = tmp_path / "material.txt"
    text.write_text("Тестовый материал", encoding="utf-8")
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic-image")
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return message_response(
            {"role": "assistant", "content": "Результат"},
            usage={"prompt_tokens": 5, "completion_tokens": 2},
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        section = run_content_scenario(client, PROVIDER, "section", text)
        vision = run_content_scenario(client, PROVIDER, "vision", image)
    assert "Тестовый материал" in requests[0]["messages"][0]["content"]
    assert requests[1]["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert section["text"] == vision["text"] == "Результат"
    assert section["cached_input_tokens"] is None


def test_cli_reports_safe_error_categories(tmp_path, monkeypatch, capsys) -> None:
    import sys

    from llm_bench.runner import main

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            [{"name": "mock", "base_url": "https://example.invalid/secret-path", "model": "model"}]
        )
    )
    input_file = tmp_path / "input.txt"
    input_file.write_text("secret-file-content", encoding="utf-8")
    real_client = httpx.Client
    modes = {
        "timeout": httpx.ReadTimeout("secret-timeout"),
        "transport": httpx.ConnectError("secret-network"),
        "http_status": httpx.Response(403, text="secret-http-body"),
        "invalid_response": httpx.Response(200, json={"choices": []}),
        "invalid_json": httpx.Response(200, text="secret-invalid-json"),
        "invalid_input": httpx.Response(200, json={"choices": []}),
    }
    for mode, outcome in modes.items():

        def handle(request: httpx.Request, outcome=outcome) -> httpx.Response:
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def make_client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        monkeypatch.setattr("llm_bench.runner.httpx.Client", make_client)
        path = tmp_path / "missing" if mode == "invalid_input" else input_file
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "runner",
                "--config",
                str(config),
                "--provider",
                "mock",
                "--scenario",
                "section",
                "--input",
                str(path),
                "--runs",
                "1",
            ],
        )
        assert main() == 1
        output = capsys.readouterr().out
        run = json.loads(output)["runs"][0]
        assert run["error"] == ("invalid_response" if mode == "invalid_json" else mode)
        assert run["duration_seconds"] >= 0
        assert run["input_tokens"] is None
        assert "secret" not in output
        if mode == "http_status":
            assert run["http_status"] == 403
        else:
            assert "http_status" not in run
