"""Проверки протокола бенчмарка на синтетическом HTTP API."""

import json
from pathlib import Path

import httpx
import pytest

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


@pytest.mark.parametrize(
    "batches",
    [
        [["edit_file", "compile", "read_file"]],
        [["read_file", "edit_file"], ["compile"]],
        [["read_file"], ["compile", "edit_file"]],
        [["edit_file"], ["read_file"], ["compile"]],
    ],
)
def test_tool_scenario_rejects_wrong_or_parallel_order(batches: list[list[str]]) -> None:
    arguments = {
        "read_file": {"path": "main.tex"},
        "edit_file": {"path": "main.tex", "old": "\\unknowncommand", "new": "world"},
        "compile": {},
    }
    replies = iter(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(name, arguments[name], i)["tool_calls"][0]
                    for i, name in enumerate(batch)
                ],
            }
            for batch in batches
        ]
        + [{"role": "assistant", "content": "Завершено"}]
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return message_response(next(replies))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = run_tool_scenario(client, PROVIDER)
    assert result["success"] is False


def test_tool_scenario_allows_compile_after_edit_in_same_response() -> None:
    edit = tool_call(
        "edit_file", {"path": "main.tex", "old": "\\unknowncommand", "new": "world"}, 2
    )
    edit["tool_calls"].append(tool_call("compile", {}, 3)["tool_calls"][0])
    replies = iter([tool_call("read_file", {"path": "main.tex"}, 1), edit])

    def handle(request: httpx.Request) -> httpx.Response:
        return message_response(next(replies))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = run_tool_scenario(client, PROVIDER)
    assert result["success"] is True
    assert result["requests"] == 2


def test_tool_scenario_rejects_noop_edit_after_read() -> None:
    replies = iter(
        [
            tool_call(
                "edit_file", {"path": "main.tex", "old": "\\unknowncommand", "new": "world"}, 1
            ),
            tool_call("read_file", {"path": "main.tex"}, 2),
            tool_call("edit_file", {"path": "main.tex", "old": "world", "new": "world"}, 3),
            tool_call("compile", {}, 4),
        ]
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return message_response(next(replies))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = run_tool_scenario(client, PROVIDER)
    assert result["success"] is False
    assert result["final_compile_ok"] is True


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


@pytest.mark.parametrize("scenario", ["section", "vision"])
@pytest.mark.parametrize(
    ("message", "reason", "expected"),
    [
        ({"content": None}, "stop", "empty_response"),
        ({"content": "  "}, "stop", "empty_response"),
        ({"content": None, "refusal": "private refusal"}, "stop", "refusal"),
        ({"content": "private incomplete text"}, "length", "truncated"),
        ({"content": None}, "content_filter", "refusal"),
    ],
)
def test_content_response_errors_are_not_success(
    tmp_path: Path, scenario: str, message: dict, reason: str, expected: str
) -> None:
    path = tmp_path / ("image.png" if scenario == "vision" else "material.txt")
    path.write_bytes(b"synthetic")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": reason}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = run_content_scenario(client, PROVIDER, scenario, path)
    assert result["error"] == expected
    assert result["finish_reason"] == reason
    assert result["input_tokens"] == 7
    assert "text" not in result
    assert "private" not in json.dumps(result)


def test_jsonl_preserves_completed_run_on_interruption(tmp_path, monkeypatch, capsys) -> None:
    import sys

    from llm_bench.runner import main

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps([{"name": "mock", "base_url": "https://example.invalid", "model": "m"}])
    )
    source = tmp_path / "input.txt"
    source.write_text("synthetic", encoding="utf-8")
    output = tmp_path / "partial.jsonl"
    real_client = httpx.Client
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return message_response({"content": "готово"})

    monkeypatch.setattr(
        "llm_bench.runner.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
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
            str(source),
            "--runs",
            "2",
            "--jsonl",
            str(output),
        ],
    )
    with pytest.raises(KeyboardInterrupt):
        main()
    saved = output.read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1
    assert json.loads(saved[0])["text"] == "готово"
    assert output.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr().out == ""


def test_jsonl_refuses_existing_file(tmp_path, monkeypatch) -> None:
    import sys

    from llm_bench.runner import main

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps([{"name": "mock", "base_url": "https://example.invalid", "model": "m"}])
    )
    output = tmp_path / "existing.jsonl"
    output.write_text("original", encoding="utf-8")
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
            "tool_calling",
            "--jsonl",
            str(output),
        ],
    )
    with pytest.raises(SystemExit):
        main()
    assert output.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize(
    ("message", "reason", "expected"),
    [
        ({"content": None, "refusal": "private refusal"}, "stop", "refusal"),
        ({"content": "private incomplete text"}, "length", "truncated"),
    ],
)
def test_cli_rejects_refusal_and_truncation(
    tmp_path, monkeypatch, capsys, message, reason, expected
) -> None:
    import sys

    from llm_bench.runner import main

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps([{"name": "mock", "base_url": "https://example.invalid", "model": "m"}])
    )
    source = tmp_path / "input.txt"
    source.write_text("synthetic", encoding="utf-8")
    output = tmp_path / "results.jsonl"
    real_client = httpx.Client

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": message, "finish_reason": reason}]}
        )

    monkeypatch.setattr(
        "llm_bench.runner.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
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
            str(source),
            "--runs",
            "1",
            "--jsonl",
            str(output),
        ],
    )
    assert main() == 1
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["runs"][0]["error"] == expected
    assert json.loads(output.read_text(encoding="utf-8"))["error"] == expected
    assert "private" not in stdout + output.read_text(encoding="utf-8")
