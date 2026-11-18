"""Локальный запуск eval-кейсов через публичный API BlaBlaTex."""

import argparse
import asyncio
import ipaddress
import json
import os
import re
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import yaml

CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z")
REPOSITORY = Path(__file__).resolve().parent.parent
TERMINAL_RUN = {"done", "failed", "cancelled"}
TERMINAL_BUILD = {"ok", "error", "timeout"}
SEQUENCED_EVENTS = {"run.delta", "run.tool_call", "run.tool_result"}


@dataclass(frozen=True)
class FinishedEvents:
    status: str
    tokens_in: int | None
    tokens_out: int | None
    last_seq: int
    compile_calls: int
    complete: bool


class CaseError(Exception):
    """Код ошибки без содержимого материалов и ответов сервера."""


def local_url(value: str) -> str:
    """Не отправлять материалы и токен за пределы локальной машины."""
    url = urlsplit(value)
    try:
        loopback = ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        loopback = url.hostname == "localhost"
    if (
        url.scheme not in {"http", "https"}
        or not loopback
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("API должен находиться на localhost или loopback")
    return value.rstrip("/")


def load_case(folder: Path) -> tuple[dict, list[tuple[str, Path]]]:
    """Читает case.yaml и только обычные файлы из materials без симлинков."""
    if folder.is_symlink() or not folder.is_dir() or not CASE_ID.fullmatch(folder.name):
        raise CaseError("invalid_case")
    case_file = folder / "case.yaml"
    materials = folder / "materials"
    if case_file.is_symlink() or materials.is_symlink() or not materials.is_dir():
        raise CaseError("invalid_case")
    try:
        case = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CaseError("invalid_case") from error
    if (
        not isinstance(case, dict)
        or case.get("id") != folder.name
        or not isinstance(case.get("meta"), dict)
    ):
        raise CaseError("invalid_case")
    root = materials.resolve(strict=True)
    files = []
    for item in materials.rglob("*"):
        if item.is_symlink():
            raise CaseError("invalid_material")
        if item.is_file():
            try:
                resolved = item.resolve(strict=True)
                relative = resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CaseError("invalid_material") from error
            if any(part.startswith(".") for part in relative.parts):
                raise CaseError("invalid_material")
            if relative.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
                raise CaseError("invalid_material")
            files.append((relative.as_posix(), resolved))
        elif not item.is_dir():
            raise CaseError("invalid_material")
    if not files:
        raise CaseError("no_materials")
    return case, sorted(files)


def _json(response: httpx.Response) -> dict:
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise CaseError("invalid_response")
    return data


def _id(value: object) -> str:
    """Ответы API используют UUID; не вставлять произвольный путь в следующий URL."""
    return str(UUID(str(value)))


async def _events(
    client: httpx.AsyncClient, project_id: str, run_id: str, message_id: str
) -> FinishedEvents | None:
    """Проверить старт, последовательность событий и финал прогона в одном потоке."""
    async with client.stream(
        "GET", f"/projects/{project_id}/events", headers={"Last-Event-ID": "0-0"}
    ) as response:
        response.raise_for_status()
        event, parts = "", []
        started = False
        complete = True
        seq = 0
        calls = 0
        async for line in response.aiter_lines():
            if not line:
                if event in SEQUENCED_EVENTS | {"run.started", "run.finished"} and parts:
                    try:
                        data = json.loads("\n".join(parts))
                        if not isinstance(data, dict):
                            complete = False
                        elif data.get("run_id") != run_id:
                            pass
                        elif event == "run.started":
                            if started or data.get("message_id") != message_id:
                                complete = False
                            started = True
                        elif event in SEQUENCED_EVENTS:
                            number = data.get("seq")
                            if not started or type(number) is not int or number != seq + 1:
                                complete = False
                            if type(number) is int and number > 0:
                                seq = number
                            if event == "run.tool_call":
                                if not isinstance(data.get("tool"), str):
                                    complete = False
                                elif data["tool"] == "compile":
                                    calls += 1
                        elif data.get("status") in TERMINAL_RUN:
                            usage = data.get("usage") or {}
                            in_tokens, out_tokens = usage.get("tokens_in"), usage.get("tokens_out")
                            return FinishedEvents(
                                status=data["status"],
                                tokens_in=in_tokens
                                if type(in_tokens) is int and in_tokens >= 0
                                else None,
                                tokens_out=out_tokens
                                if type(out_tokens) is int and out_tokens >= 0
                                else None,
                                last_seq=seq,
                                compile_calls=calls,
                                complete=started and complete,
                            )
                    except (ValueError, TypeError, AttributeError):
                        complete = False
                elif event in SEQUENCED_EVENTS | {"run.started", "run.finished"}:
                    complete = False
                event, parts = "", []
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                parts.append(line[5:].lstrip())
    return None


async def _poll_message(
    client: httpx.AsyncClient, project_id: str, message_id: str
) -> tuple[str, int | None] | None:
    data = _json(await client.get(f"/projects/{project_id}/messages", params={"limit": 100}))
    for item in data.get("items", []):
        if item.get("id") == message_id and item.get("status") in TERMINAL_RUN:
            seq = item.get("seq")
            return item["status"], seq if type(seq) is int and seq >= 0 else None
    return None


async def wait_run(
    client: httpx.AsyncClient, project_id: str, run_id: str, message_id: str, timeout_s: float
) -> tuple[str, int | None, int | None, int | None]:
    """Читает SSE параллельно с проверкой чата; при потере событий расход неизвестен."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    task = asyncio.create_task(_events(client, project_id, run_id, message_id))

    async def finish(event: FinishedEvents) -> tuple[str, int | None, int | None, int | None]:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0.02:
            return event.status, event.tokens_in, event.tokens_out, None
        try:
            message = await asyncio.wait_for(
                _poll_message(client, project_id, message_id), timeout=min(2, remaining - 0.01)
            )
        except (TimeoutError, httpx.HTTPError, CaseError, ValueError, TypeError, AttributeError):
            message = None
        count = None
        if event.complete and message == (event.status, event.last_seq):
            count = event.compile_calls
        return event.status, event.tokens_in, event.tokens_out, count

    try:
        async with asyncio.timeout(timeout_s):
            while True:
                result = None
                if task is not None:
                    try:
                        result = await asyncio.wait_for(asyncio.shield(task), timeout=2)
                    except TimeoutError:
                        pass
                    except (httpx.HTTPError, CaseError):
                        task = None
                    else:
                        if result is None:
                            task = None
                else:
                    await asyncio.sleep(2)
                if result:
                    return await finish(result)
                message = await _poll_message(client, project_id, message_id)
                if message:
                    # Событие может прийти немного позже фиксации сообщения в БД.
                    if task is not None:
                        try:
                            result = await asyncio.wait_for(
                                asyncio.shield(task),
                                timeout=max(
                                    0.001, min(2, deadline - asyncio.get_running_loop().time())
                                ),
                            )
                        except (TimeoutError, httpx.HTTPError, CaseError):
                            pass
                        if result:
                            count = (
                                result.compile_calls
                                if result.complete and message == (result.status, result.last_seq)
                                else None
                            )
                            return result.status, result.tokens_in, result.tokens_out, count
                    return message[0], None, None, None
    except TimeoutError as error:
        raise CaseError("run_timeout") from error
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def section_files(client: httpx.AsyncClient, project_id: str, case: dict) -> dict:
    """Наличие файла раздела по руководству и дереву; заполненность не проверяется."""
    expected = case.get("expected")
    sections = expected.get("sections", []) if isinstance(expected, dict) else []
    if not isinstance(sections, list) or any(not isinstance(name, str) for name in sections):
        raise CaseError("invalid_case")
    result = dict.fromkeys(sections)
    if not result:
        return result
    try:
        guide = _json(await client.get(f"/projects/{project_id}/template-guide"))
        tree = _json(await client.get(f"/projects/{project_id}/tree"))
        guide_sections, items = guide["sections"], tree["items"]
        if not isinstance(guide_sections, list) or not isinstance(items, list):
            return result
        paths = {item["path"] for item in items if item.get("kind") != "folder"}
        for title in result:
            matches = [s for s in guide_sections if s.get("title") == title]
            if len(matches) == 1 and isinstance(matches[0].get("file"), str):
                result[title] = matches[0]["file"] in paths
    except (httpx.HTTPError, CaseError, KeyError, TypeError, ValueError, AttributeError):
        return dict.fromkeys(sections)
    return result


def result_for(case_id: str) -> dict:
    return {
        "schema_version": 1,
        "case_id": case_id,
        "project_id": None,
        "run_id": None,
        "run_status": None,
        "build_id": None,
        "build_status": None,
        "pdf_downloaded": False,
        "tokens_in": None,
        "tokens_out": None,
        "cost": None,
        "compile_calls": None,
        "section_files": {},
        "error": None,
    }


def save_pdf(output: Path, case_id: str, content: bytes) -> None:
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = output / f"{case_id}.pdf"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(content)


async def run_case(
    client: httpx.AsyncClient, folder: Path, output: Path, *, timeout_s: float = 300
) -> dict:
    """Создаёт отдельный проект, передаёт материалы, ждёт агента и собирает PDF."""
    result = result_for(folder.name)
    try:
        case, files = await asyncio.to_thread(load_case, folder)
        body = {"title": folder.name, "template_slug": "mtuci-lab", "fields": case["meta"]}
        project = _json(await client.post("/projects", json=body))
        project_id = _id(project["id"])
        result["project_id"] = project_id
        # Один запрос на папку: совпадающие имена в разных папках не перезаписываются.
        groups: dict[str, list[Path]] = {}
        for relative, path in files:
            parent = Path(relative).parent.as_posix()
            dest = "materials" if parent == "." else f"materials/{parent}"
            groups.setdefault(dest, []).append(path)
        for dest, group in groups.items():
            for i in range(0, len(group), 100):
                with ExitStack() as stack:
                    parts = [
                        ("files", (path.name, stack.enter_context(path.open("rb"))))
                        for path in group[i : i + 100]
                    ]
                    _json(
                        await client.post(
                            f"/projects/{project_id}/upload", data={"dir": dest}, files=parts
                        )
                    )
        created = _json(
            await client.post(f"/projects/{project_id}/messages", json={"text": "Сделай отчёт"})
        )
        run = created["run"]
        result["run_id"] = _id(run["id"])
        status, tokens_in, tokens_out, compile_calls = await wait_run(
            client, project_id, result["run_id"], _id(run["message_id"]), timeout_s
        )
        result.update(
            run_status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            compile_calls=compile_calls,
        )
        if status != "done":
            raise CaseError("run_not_done")
        result["section_files"] = await section_files(client, project_id, case)
        build = _json(await client.post(f"/projects/{project_id}/builds"))
        result["build_id"] = _id(build["id"])
        async with asyncio.timeout(timeout_s):
            while build.get("status") not in TERMINAL_BUILD:
                build = _json(
                    await client.get(f"/builds/{result['build_id']}", params={"wait": 60})
                )
        result["build_status"] = build["status"]
        if build["status"] == "error":
            raise CaseError("build_failed")
        if build["status"] == "timeout":
            raise CaseError("build_timeout")
        if build.get("has_pdf") is not True:
            raise CaseError("pdf_missing")
        response = await client.get(f"/builds/{result['build_id']}/pdf")
        response.raise_for_status()
        if not response.content.startswith(b"%PDF-"):
            raise CaseError("invalid_pdf")
        await asyncio.to_thread(save_pdf, output, folder.name, response.content)
        result["pdf_downloaded"] = True
    except CaseError as error:
        result["error"] = str(error)
    except (httpx.TimeoutException, TimeoutError):
        result["error"] = "timeout"
    except httpx.HTTPStatusError:
        result["error"] = "http_status"
    except httpx.RequestError:
        result["error"] = "transport"
    except (KeyError, TypeError, ValueError, AttributeError):
        result["error"] = "invalid_response"
    except OSError:
        result["error"] = "file_error"
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description="Локальный eval через API BlaBlaTex")
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("EVAL_DATA_DIR"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8765/api/v1")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    if args.data_dir is None or args.timeout <= 0:
        parser.error("Укажите EVAL_DATA_DIR и положительный timeout")
    try:
        url = local_url(args.url)
    except ValueError:
        parser.error("API должен находиться на localhost или loopback")
    token = os.environ.get("BLABLATEX_TOKEN")
    if not token:
        parser.error("Не задан BLABLATEX_TOKEN")
    if args.data_dir.is_symlink() or not args.data_dir.is_dir():
        parser.error("EVAL_DATA_DIR должен быть локальным каталогом")
    if args.output_dir.resolve().is_relative_to(args.data_dir.resolve()):
        parser.error("Каталог результатов должен быть отдельно от EVAL_DATA_DIR")
    if args.output_dir.resolve().is_relative_to(REPOSITORY):
        parser.error("Каталог результатов должен быть вне репозитория")
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    failed = False
    processed = 0
    async with httpx.AsyncClient(
        base_url=url + "/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=75,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        for folder in sorted(args.data_dir.iterdir()):
            if not folder.is_dir() or not (folder / "case.yaml").exists():
                continue
            processed += 1
            result = await run_case(client, folder, args.output_dir, timeout_s=args.timeout)
            failed |= result["error"] is not None or result["build_status"] != "ok"
            path = args.output_dir / f"{folder.name}.json"
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
    return int(failed or processed == 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
