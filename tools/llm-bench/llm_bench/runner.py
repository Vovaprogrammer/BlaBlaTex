"""Сценарии бенчмарка OpenAI-совместимого Chat Completions API."""

import argparse
import base64
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any  # JSON OpenAI API содержит произвольные вложенные поля.

import httpx

from llm_bench.config import Provider, load_config

BROKEN = "\\documentclass{article}\n\\begin{document}\nHello \\unknowncommand\n\\end{document}\n"
FIXED = "\\documentclass{article}\n\\begin{document}\nHello world\n\\end{document}\n"
TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }
    for name, description, properties, required in [
        ("read_file", "Прочитать main.tex", {"path": {"type": "string"}}, ["path"]),
        (
            "edit_file",
            "Заменить единственное вхождение old на new в main.tex",
            {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
            ["path", "old", "new"],
        ),
        ("compile", "Проверить исправленный документ", {}, []),
    ]
]


class InvalidResponse(Exception):
    """Ответ API не соответствует ожидаемому формату."""


class FakeDocument:
    """Фейковый документ: успех только после точной правки и проверки сборки."""

    def __init__(self) -> None:
        self.content = BROKEN
        self.compiled = False
        self.called = set()

    def call(self, name: str, args: dict[str, Any]) -> str:
        if name == "read_file" and args.get("path") == "main.tex":
            self.called.add(name)
            return self.content
        if name == "edit_file" and args.get("path") == "main.tex":
            old, new = args.get("old"), args.get("new")
            if not isinstance(old, str) or not isinstance(new, str) or not old:
                return "Ошибка: ожидаются непустой old и строка new"
            if self.content.count(old) != 1:
                return "Ошибка: old должен встречаться ровно один раз"
            self.content = self.content.replace(old, new, 1)
            self.called.add(name)
            self.compiled = False
            return "Файл изменён"
        if name == "compile":
            self.called.add(name)
            self.compiled = self.content == FIXED
            return "Сборка успешна" if self.compiled else "Ошибка: некорректное содержимое main.tex"
        return "Неизвестный инструмент или путь"


class Usage:
    def __init__(self) -> None:
        self.calls = 0
        self.values: dict[str, int | None] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
        }

    def add(self, response: dict[str, Any]) -> None:
        self.calls += 1
        usage = response.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        for key, value in (
            ("input_tokens", usage.get("prompt_tokens")),
            ("output_tokens", usage.get("completion_tokens")),
            ("cached_input_tokens", details.get("cached_tokens")),
        ):
            previous = self.values[key]
            if (
                previous is None
                or not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                self.values[key] = None
            else:
                self.values[key] = previous + value


def chat(
    client: httpx.Client,
    provider: Provider,
    messages: list[dict[str, Any]],
    usage: Usage,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str | None]:
    payload: dict[str, Any] = {"model": provider.model, "messages": messages}
    if tools is not None:
        payload["tools"] = tools
    response = client.post(f"{provider.base_url}/chat/completions", json=payload)
    response.raise_for_status()
    try:
        data = response.json()
        usage.add(data)
        choice = data["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise TypeError
        reason = choice.get("finish_reason")
        if reason not in ("stop", "length", "content_filter", "tool_calls", "function_call"):
            reason = None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise InvalidResponse from error
    return message, reason


def run_tool_scenario(client: httpx.Client, provider: Provider) -> dict[str, Any]:
    document, usage = FakeDocument(), Usage()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "Исправь ошибку в main.tex, затем проверь сборку."},
        {"role": "user", "content": "Документ должен содержать текст Hello world."},
    ]
    start = time.monotonic()
    for _ in range(8):
        message, _ = chat(client, provider, messages, usage, TOOL_SPECS)
        calls = message.get("tool_calls") or []
        if not calls:
            break
        messages.append(message)
        for call in calls:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments", "{}"))
                if not isinstance(arguments, dict):
                    raise ValueError("Нужен объект")
                result = document.call(function.get("name", ""), arguments)
            except (json.JSONDecodeError, ValueError):
                result = "Некорректные аргументы"
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        if document.compiled:
            break
    return {
        "scenario": "tool_calling",
        "success": document.compiled and {"read_file", "edit_file", "compile"} <= document.called,
        "tools_called": {
            name: name in document.called for name in ("read_file", "edit_file", "compile")
        },
        "final_compile_ok": document.compiled,
        "duration_seconds": round(time.monotonic() - start, 3),
        **usage.values,
        "requests": usage.calls,
    }


def run_content_scenario(
    client: httpx.Client, provider: Provider, scenario: str, path: Path
) -> dict[str, Any]:
    if scenario == "section":
        content: Any = "Напиши раздел «Ход работы» только по материалу:\n\n" + path.read_text(
            encoding="utf-8"
        )
    else:
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
            path.suffix.lower()
        )
        if mime is None:
            raise ValueError("Для vision нужен PNG или JPEG")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": "Опиши скриншот и перепиши видимый текст без догадок."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]
    usage = Usage()
    start = time.monotonic()
    message, reason = chat(client, provider, [{"role": "user", "content": content}], usage)
    result = {
        "scenario": scenario,
        "duration_seconds": round(time.monotonic() - start, 3),
        "finish_reason": reason,
        **usage.values,
        "requests": usage.calls,
    }
    text = message.get("content")
    if message.get("refusal") or reason == "content_filter":
        result["error"] = "refusal"
    elif reason == "length":
        result["error"] = "truncated"
    elif not isinstance(text, str) or not text.strip():
        result["error"] = "empty_response"
    else:
        result["text"] = text
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Бенчмарк модели на отдельных сценариях")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--scenario", choices=["tool_calling", "section", "vision"], required=True)
    parser.add_argument("--input", type=Path, help="Текст материала или изображение")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--jsonl", type=Path, help="Новый файл для сохранения каждого прогона")
    args = parser.parse_args()
    if args.runs < 1 or args.runs > 100 or args.timeout <= 0:
        parser.error("--runs должен быть от 1 до 100, --timeout — положительным")
    if args.scenario != "tool_calling" and args.input is None:
        parser.error("Для section и vision требуется --input")
    providers = [p for p in load_config(args.config) if p.name == args.provider]
    if not providers:
        parser.error("Провайдер не найден")
    provider = providers[0]
    headers = {}
    if provider.api_key_env:
        key = os.environ.get(provider.api_key_env)
        if not key:
            parser.error("Не задана переменная ключа провайдера")
        headers["Authorization"] = f"Bearer {key}"
    results = []
    try:
        output = (
            os.fdopen(
                os.open(args.jsonl, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                "w",
                encoding="utf-8",
            )
            if args.jsonl is not None
            else contextlib.nullcontext(None)
        )
    except OSError:
        parser.error("Не удалось создать новый файл JSONL")
    with (
        output as progress,
        httpx.Client(headers=headers, timeout=args.timeout, trust_env=False) as client,
    ):
        for _ in range(args.runs):
            start = time.monotonic()
            try:
                if args.scenario == "tool_calling":
                    result = run_tool_scenario(client, provider)
                else:
                    result = run_content_scenario(client, provider, args.scenario, args.input)
            except httpx.TimeoutException:
                result = {"scenario": args.scenario, "error": "timeout"}
            except httpx.HTTPStatusError as error:
                result = {
                    "scenario": args.scenario,
                    "error": "http_status",
                    "http_status": error.response.status_code,
                }
            except httpx.RequestError:
                result = {"scenario": args.scenario, "error": "transport"}
            except (InvalidResponse, KeyError, IndexError, TypeError, AttributeError):
                result = {"scenario": args.scenario, "error": "invalid_response"}
            except (ValueError, OSError):
                result = {"scenario": args.scenario, "error": "invalid_input"}
            if "error" in result:
                result.setdefault("duration_seconds", round(time.monotonic() - start, 3))
                for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
                    result.setdefault(key, None)
            results.append(result)
            if progress is not None:
                entry = {
                    "provider": provider.name,
                    "model": provider.model,
                    "run": len(results),
                    **result,
                }
                progress.write(json.dumps(entry, ensure_ascii=False) + "\n")
                progress.flush()
    report = {"provider": provider.name, "model": provider.model, "runs": results}
    if args.scenario == "tool_calling":
        report["successes"] = sum(result.get("success") is True for result in results)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 1 if any("error" in result for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
