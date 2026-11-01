"""Запуск latexmk с таймаутом в отдельной группе процессов (architecture.md 6)."""

import asyncio
import os
import signal
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# LuaLaTeX не работает при openin_any=p — причина в architecture.md, раздел 6.
Engine = Literal["xelatex", "pdflatex"]
Status = Literal["ok", "error", "timeout"]

OUT_DIR = "out"
# Любой файл, который пишет сборка, — не больше 64 МБ: PDF по 9.8 до 50 МБ, а лог
# бесконечного \message без лимита съел бы всю память tmpfs.
MAX_OUTPUT_FILE_BYTES = 64 * 1024 * 1024

# Сборка получает только эти переменные окружения сервиса: прочитать через
# /proc/self/environ можно лишь то, что нужно TeX.
_TEX_ENV_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TEXINPUTS",
    "openin_any",
    "openout_any",
    "shell_escape",
)


@dataclass(frozen=True)
class RunResult:
    status: Status
    exit_code: int | None
    duration_ms: int


def latexmk_command(engine: Engine, main: str) -> list[str]:
    """Команда сборки. main проверен заранее и не начинается с «-»: иначе это опция latexmk.

    Меняете команду — поднимите COMPILER_VERSION в Dockerfile: от неё зависит кэш сборок.
    """
    return [
        # prlimit ставит лимит на размер файлов и сразу запускает latexmk в том же процессе.
        "prlimit",
        f"--fsize={MAX_OUTPUT_FILE_BYTES}",
        "--",
        "latexmk",
        # -norc: файлы latexmkrc — это Perl-код, их не читаем ни из проекта, ни из системы.
        "-norc",
        f"-{engine}",
        "-interaction=nonstopmode",
        "-file-line-error",
        "-synctex=1",
        "-no-shell-escape",
        f"-outdir={OUT_DIR}",
        main,
    ]


def tex_env() -> dict[str, str]:
    return {key: os.environ[key] for key in _TEX_ENV_KEYS if key in os.environ}


async def run_latexmk(
    workdir: Path, console: Path, engine: Engine, main: str, timeout_s: int
) -> RunResult:
    """Собирает main в workdir; вывод latexmk пишет в console (вне workdir).

    По таймауту убивает всю группу процессов: latexmk, xelatex, xdvipdfmx, bibtex.
    Вывод идёт в файл, а не в pipe: так он не копится в памяти сервиса.
    """
    console_fd = os.open(console, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *latexmk_command(engine, main),
            cwd=workdir,
            env=tex_env(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=console_fd,
            stderr=asyncio.subprocess.STDOUT,
            # Своя сессия = своя группа процессов с номером process.pid.
            start_new_session=True,
        )
    finally:
        os.close(console_fd)

    status: Status
    exit_code: int | None
    try:
        exit_code = await asyncio.wait_for(process.wait(), timeout_s)
        status = "ok" if exit_code == 0 else "error"
    except TimeoutError:
        status, exit_code = "timeout", None
    finally:
        # Добиваем группу и после обычного завершения: вдруг кто-то остался в фоне.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
    return RunResult(status, exit_code, round((time.monotonic() - started) * 1000))
