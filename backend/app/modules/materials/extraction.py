"""Извлечение текста из материалов (architecture.md 5): что ИИ прочитает в файле.

Документы (.pdf .docx .pptx .xlsx) разбираются в отдельном процессе — materials/convert.py:
файлы чужие и непроверенные, а разбор может зависнуть или съесть всю память. Процесс не
получает секретов, его память ограничена, по сроку он убивается. Event loop воркера при
этом не блокируется. Одновременно воркер разбирает не больше CONCURRENCY документов.
"""

import asyncio
import os
import sys
import weakref
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from app.modules.materials.schemas import MaterialMethod
from app.modules.projects.filetypes import DOCX_MIME, PPTX_MIME, XLSX_MIME
from app.modules.projects.paths import BINARY_FILE_TYPES

CONVERTER = Path(__file__).with_name("convert.py")

# Документы, текст которых достаёт convert.py: MIME из 9.8 → вид документа.
DOCUMENT_KINDS: dict[str, str] = {
    BINARY_FILE_TYPES[".pdf"]: "pdf",
    DOCX_MIME: "docx",
    PPTX_MIME: "pptx",
    XLSX_MIME: "xlsx",
}

# Сколько документов воркер разбирает одновременно: каждый — отдельный процесс до memory_mb.
CONCURRENCY = 2

# Переменные окружения, без которых процесс разбора не запустится. Остальные, в том числе
# секреты воркера (адрес базы, ключи), процесс не получает.
_CHILD_ENV_KEYS = ("PATH", "SYSTEMROOT", "TEMP", "TMP")
# Библиотеки чисел (pandas внутри markitdown) не заводят лишних потоков и памяти под них.
_CHILD_THREADS_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}

BROKEN_MESSAGE = (
    "Не удалось прочитать текст из файла: возможно, он повреждён. "
    "Откройте его, сохраните заново и загрузите ещё раз."
)
TIMEOUT_MESSAGE = (
    "Файл обрабатывался слишком долго. Если это большой документ, загрузите только нужные страницы."
)
UNSUPPORTED_MESSAGE = "Из файлов этого типа ИИ текст не читает."


@dataclass(frozen=True)
class Limits:
    """Пределы разбора одного документа (architecture.md 5)."""

    timeout_s: float = 60
    memory_mb: int = 1024


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Extracted:
    """Итог извлечения: текст для ИИ, число страниц или слайдов и чем получен текст."""

    text: str | None
    pages: int | None
    method: MaterialMethod


class ExtractionFailed(Exception):
    """Текст не извлёкся. message — для студента, на русском; detail — для лога, без
    содержимого файла."""

    def __init__(self, message: str, detail: dict[str, str | int] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class ConverterOutput(BaseModel):
    """Итог convert.py: текст или ошибка разбора."""

    text: str | None = None
    pages: int | None = None
    method: MaterialMethod | None = None
    error: str | None = None
    error_type: str | None = None
    trace: str | None = None


@dataclass
class _Slots:
    """Семафор на каждый event loop: в тестах у каждого теста свой loop."""

    by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = field(
        default_factory=weakref.WeakKeyDictionary
    )

    def get(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if loop not in self.by_loop:
            self.by_loop[loop] = asyncio.Semaphore(CONCURRENCY)
        return self.by_loop[loop]


_slots = _Slots()


async def extract(mime: str | None, data: bytes, limits: Limits = DEFAULT_LIMITS) -> Extracted:
    """Текст материала по его MIME из 9.8. Не вышло — ExtractionFailed."""
    kind = DOCUMENT_KINDS.get(mime or "")
    if kind is None:
        raise ExtractionFailed(UNSUPPORTED_MESSAGE, {"reason": "unsupported", "mime": mime or ""})
    output = await _convert(kind, data, limits)
    if output.error is not None or output.method is None:
        raise ExtractionFailed(
            BROKEN_MESSAGE,
            {
                "reason": output.error or "no_result",
                "error_type": output.error_type or "",
                "trace": output.trace or "",
            },
        )
    return Extracted(text=output.text, pages=output.pages, method=output.method)


async def _convert(kind: str, data: bytes, limits: Limits) -> ConverterOutput:
    """Запускает convert.py и ждёт итог не дольше limits.timeout_s; не дождался — убивает."""
    async with _slots.get():
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            # -I: без PYTHONPATH, пользовательских пакетов и папки скрипта в sys.path.
            "-I",
            "-X",
            "utf8",
            str(CONVERTER),
            kind,
            str(limits.memory_mb),
            stdin=PIPE,
            stdout=PIPE,
            # Предупреждения библиотек разбора не нужны и могут цитировать файл.
            stderr=DEVNULL,
            env=_child_env(),
        )
        try:
            async with asyncio.timeout(limits.timeout_s):
                stdout, _ = await process.communicate(data)
        except TimeoutError:
            raise ExtractionFailed(TIMEOUT_MESSAGE, {"reason": "timeout", "kind": kind}) from None
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    if process.returncode != 0:
        raise ExtractionFailed(
            BROKEN_MESSAGE, {"reason": "crashed", "kind": kind, "returncode": process.returncode}
        )
    return ConverterOutput.model_validate_json(stdout)


def _child_env() -> dict[str, str]:
    """Окружение процесса разбора: только то, без чего он не запустится."""
    # Это не настройки сервиса (их читает только core/config.py), а белый список того,
    # что передаётся дальше чужому файлу: всё остальное окружение воркера отрезается.
    env = {key: os.environ[key] for key in _CHILD_ENV_KEYS if key in os.environ}
    return env | _CHILD_THREADS_ENV
