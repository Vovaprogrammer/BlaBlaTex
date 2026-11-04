"""Извлечение текста из материалов (architecture.md 5): что ИИ прочитает в файле.

- Текст и код берутся как есть.
- Документы (.pdf .docx .pptx .xlsx) разбираются в отдельном процессе — materials/convert.py:
  файлы чужие и непроверенные, а разбор может зависнуть или съесть всю память. Процесс не
  получает секретов, его память ограничена, по сроку он убивается. Event loop воркера при
  этом не блокируется. Одновременно воркер обрабатывает не больше CONCURRENCY материалов:
  место (slot) задача занимает до того, как взять материал в работу.
- Картинки .png и .jpg — без текста: их описывает vision-модель, если это включено.
- Остальное (.svg) — понятная ошибка.

Текст длиннее Limits.max_chars обрезается с пометкой в конце.
"""

import asyncio
import json
import os
import sys
import weakref
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

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
# Картинки, которые может описать vision-модель (как get_image в 9.4).
IMAGE_MIMES = frozenset({BINARY_FILE_TYPES[".png"], BINARY_FILE_TYPES[".jpg"]})
SVG_MIME = BINARY_FILE_TYPES[".svg"]

# Сколько материалов воркер обрабатывает одновременно: документ — отдельный процесс до memory_mb.
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
TOO_COMPLEX_MESSAGE = (
    "Файл слишком сложный: на его обработку не хватило памяти. "
    "Сохраните его заново или загрузите только нужные страницы."
)
PASSWORD_MESSAGE = (
    "PDF защищён паролем, поэтому ИИ не может его прочитать. "
    "Снимите защиту и загрузите файл ещё раз."
)
NO_TEXT_MESSAGE = (
    "В PDF нет текста — похоже, это скан или фотографии страниц. "
    "ИИ пока не читает сканы: загрузите PDF с текстом или перепечатайте задание."
)
ARCHIVE_MESSAGE = (
    "Документ слишком большой в распакованном виде — так бывает с повреждёнными "
    "или подозрительными файлами. Сохраните его заново без лишних вложений."
)
SVG_MESSAGE = (
    "ИИ не читает картинки SVG. Чтобы он увидел картинку, загрузите её в формате PNG или JPG."
)
UNSUPPORTED_MESSAGE = "Из файлов этого типа ИИ текст не читает."
TRUNCATED_NOTE = "[Текст обрезан: сохранены первые {kept} символов из {total}.]"

# Код ошибки из convert.py → сообщение студенту.
_FAILURES = {
    "broken": BROKEN_MESSAGE,
    "too_complex": TOO_COMPLEX_MESSAGE,
    "password": PASSWORD_MESSAGE,
    "no_text": NO_TEXT_MESSAGE,
    "archive_too_large": ARCHIVE_MESSAGE,
}


@dataclass(frozen=True)
class Limits:
    """Пределы извлечения одного материала (architecture.md 5)."""

    timeout_s: float = 60
    memory_mb: int = 1024
    # Сколько символов текста хранится; длиннее — обрезка с пометкой.
    max_chars: int = 500_000
    # Документ Office — архив ZIP: столько он может занимать распакованным и столько частей
    # в нём может быть. Больше — похоже на zip-бомбу, документ не разбирается.
    max_unpacked_bytes: int = 200 * 1024 * 1024
    max_parts: int = 10_000


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
    """Итог convert.py: текст (не длиннее max_chars) и длина всего текста — или ошибка."""

    text: str | None = None
    total: int = 0
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


def slot() -> asyncio.Semaphore:
    """Место для обработки одного материала: `async with slot():`. Задача занимает его до
    того, как взять материал в работу, — иначе, пока она ждёт места, фоновая проверка решит,
    что задание потерялось, и итог пропадёт."""
    return _slots.get()


async def extract(
    mime: str | None, content: str | bytes, limits: Limits = DEFAULT_LIMITS
) -> Extracted:
    """Текст материала. content — текст текстового файла или байты бинарного, mime — из 9.8.

    Не вышло — ExtractionFailed с сообщением для студента.
    """
    if isinstance(content, str):
        text = truncated(content[: limits.max_chars], len(content), limits.max_chars)
        return Extracted(text=text, pages=None, method="text")
    if mime in IMAGE_MIMES:
        return Extracted(text=None, pages=None, method="image")
    if mime == SVG_MIME:
        raise ExtractionFailed(SVG_MESSAGE, {"reason": "svg"})
    kind = DOCUMENT_KINDS.get(mime or "")
    if kind is None:
        raise ExtractionFailed(UNSUPPORTED_MESSAGE, {"reason": "unsupported", "mime": mime or ""})
    output = await _convert(kind, content, limits)
    if output.error is not None or output.method is None or output.text is None:
        reason = output.error or "no_result"
        raise ExtractionFailed(
            _FAILURES.get(reason, BROKEN_MESSAGE),
            {
                "reason": reason,
                "kind": kind,
                "error_type": output.error_type or "",
                "trace": output.trace or "",
            },
        )
    text = truncated(output.text, output.total, limits.max_chars)
    return Extracted(text=text, pages=output.pages, method=output.method)


def truncated(text: str, total: int, max_chars: int) -> str:
    """text — начало текста длиной total. Длиннее max_chars — обрезка по концу строки
    и пометка в конце, чтобы ИИ знал, что дальше было ещё."""
    if total <= max_chars:
        return text
    kept = text[:max_chars]
    line_end = kept.rfind("\n")
    # Строка без переносов на полтекста — режем как есть, а не теряем половину.
    if line_end > max_chars // 2:
        kept = kept[:line_end]
    kept = kept.rstrip()
    note = TRUNCATED_NOTE.format(kept=_number(len(kept)), total=_number(total))
    return f"{kept}\n\n{note}"


def _number(value: int) -> str:
    """500000 → «500 000»."""
    return f"{value:,}".replace(",", " ")


async def _convert(kind: str, data: bytes, limits: Limits) -> ConverterOutput:
    """Запускает convert.py и ждёт итог не дольше limits.timeout_s; не дождался — убивает."""
    options = {key: value for key, value in asdict(limits).items() if key != "timeout_s"}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        # -I: без PYTHONPATH, пользовательских пакетов и папки скрипта в sys.path.
        "-I",
        "-X",
        "utf8",
        str(CONVERTER),
        kind,
        json.dumps(options),
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
        # Процесс разбора не дожил до итога — почти всегда это лимит памяти.
        raise ExtractionFailed(
            TOO_COMPLEX_MESSAGE,
            {"reason": "crashed", "kind": kind, "returncode": process.returncode},
        )
    try:
        return ConverterOutput.model_validate_json(stdout)
    except ValidationError:
        # Текст этой ошибки цитирует вывод процесса, а в нём — текст файла: в лог только причина.
        raise ExtractionFailed(BROKEN_MESSAGE, {"reason": "bad_output", "kind": kind}) from None


def _child_env() -> dict[str, str]:
    """Окружение процесса разбора: только то, без чего он не запустится."""
    # Это не настройки сервиса (их читает только core/config.py), а белый список того,
    # что передаётся дальше чужому файлу: всё остальное окружение воркера отрезается.
    env = {key: os.environ[key] for key in _CHILD_ENV_KEYS if key in os.environ}
    return env | _CHILD_THREADS_ENV
