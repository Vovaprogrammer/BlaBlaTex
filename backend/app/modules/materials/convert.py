"""Разбор документа или ноутбука в отдельном процессе (architecture.md 5).
Запускает его materials/extraction.py.

`python -I -X utf8 convert.py <kind> <options JSON>`: файл приходит в stdin, итог — JSON
в stdout. Файлы чужие и непроверенные, поэтому разбор — не в процессе воркера: здесь нет ни
секретов в окружении, ни соединений с базой, память ограничена, а родитель убивает процесс
по сроку. Модуль ничего не импортирует из app: его запускают как отдельный скрипт.

Итог: {"text", "total", "pages", "method"} — text не длиннее max_chars, total — длина всего
текста; или {"error", "error_type", "trace"}. В trace — только где упал разбор, без текста
исключения: в нём может оказаться кусок файла.
"""

import io
import json
import re
import sys
import traceback
import zipfile
from typing import Any

PAGE_MARKER = "<!-- Страница {} -->"
# Так markitdown отмечает начало каждого слайда.
SLIDE_MARKER = re.compile(r"^<!-- Slide number: \d+ -->$", re.MULTILINE)

# Ноутбук: подпись под кодом ячейки, пометка вместо картинки и ошибка ячейки.
OUTPUT_LABEL = "Вывод:"
IMAGE_MARK = "[рисунок]"
ERROR_LINE = "Ошибка: {name}: {value}"
# Вывод ячейки длиннее — только начало и конец: одна ячейка, напечатавшая весь датасет,
# иначе вытеснила бы за предел текста все результаты ниже.
OUTPUT_LIMIT = 20_000
OUTPUT_SKIPPED = "[… пропущено {skipped} символов вывода …]"
# Цветовые и прочие управляющие коды терминала (ESC [ … буква).
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_BACKTICKS = re.compile(r"`+")
# Язык блока кода — одно слово: python, r, julia, c++.
_LANGUAGE = re.compile(r"[\w+#.-]{1,30}")

# Any: итог уходит в JSON, его проверяет родитель (extraction.ConverterOutput).
Result = dict[str, Any]


class Failure(Exception):
    """Разбор невозможен по понятной причине: code — ключ сообщения в extraction.py."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def limit_memory(memory_mb: int) -> None:
    """Лимит памяти процесса. Он есть на Linux (прод и CI); на Windows (dev) — без лимита."""
    try:
        import resource
    except ImportError:
        return
    limit = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def convert_pdf(data: bytes) -> Result:
    """Текст PDF по страницам: перед каждой — маркер с номером. Нет текста нигде — скан."""
    from pdfminer.high_level import extract_text

    pages = extract_text(io.BytesIO(data)).split("\f")
    # pdfminer ставит \f после каждой страницы, поэтому за последним \f — пустой хвост.
    if pages[-1].strip() == "":
        pages.pop()
    if not any(page.strip() for page in pages):
        raise Failure("no_text")
    text = "\n\n".join(
        f"{PAGE_MARKER.format(number)}\n{page.strip()}".rstrip()
        for number, page in enumerate(pages, start=1)
    )
    return {"text": text, "pages": len(pages), "method": "pdfminer"}


def check_archive(data: bytes, max_unpacked_bytes: int, max_parts: int) -> None:
    """Документ Office — архив ZIP. Распакованный больше предела или из слишком многих
    частей — похоже на zip-бомбу. Размеры берутся из оглавления архива: больше заявленного
    zipfile не распакует, а соврать в меньшую сторону мешает проверка CRC."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = archive.infolist()
    if len(parts) > max_parts or sum(part.file_size for part in parts) > max_unpacked_bytes:
        raise Failure("archive_too_large")


def convert_office(kind: str, data: bytes) -> Result:
    """docx, pptx и xlsx — в markdown через markitdown. У презентации pages — число слайдов."""
    from markitdown import StreamInfo
    from markitdown.converters import DocxConverter, PptxConverter, XlsxConverter

    converters = {"docx": DocxConverter, "pptx": PptxConverter, "xlsx": XlsxConverter}
    result = converters[kind]().convert(io.BytesIO(data), StreamInfo(extension=f".{kind}"))
    text = result.markdown
    pages = len(SLIDE_MARKER.findall(text)) if kind == "pptx" else None
    return {"text": text, "pages": pages, "method": "markitdown"}


def convert_notebook(data: bytes) -> Result:
    """Ноутбук Jupyter (nbformat 4): ячейки по порядку, под кодом — его вывод.

    markitdown читает ноутбуки, но выбрасывает вывод ячеек, а для отчёта он и нужен: замеры,
    результаты проверок. Картинка из вывода — пометка «[рисунок]».
    """
    try:
        notebook = json.loads(data.decode("utf-8-sig"))
    # Не UTF-8 и не JSON — ValueError, слишком глубокая вложенность — RecursionError.
    except (ValueError, RecursionError):
        raise Failure("notebook") from None
    cells = notebook.get("cells") if isinstance(notebook, dict) else None
    if not isinstance(cells, list):
        raise Failure("notebook")
    language = _notebook_language(notebook.get("metadata"))
    parts: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        source = _joined(cell.get("source")).strip("\n")
        if cell.get("cell_type") != "code":
            if source.strip():
                parts.append(source)
            continue
        if source.strip():
            parts.append(_fenced(source, language))
        output = _cell_output(cell.get("outputs"))
        if output:
            parts.append(f"{OUTPUT_LABEL}\n{output}")
    return {"text": "\n\n".join(parts), "pages": None, "method": "notebook"}


def _notebook_language(metadata: object) -> str:
    """Язык кода из метаданных ноутбука или пустая строка."""
    if not isinstance(metadata, dict):
        return ""
    for key, field in (("language_info", "name"), ("kernelspec", "language")):
        section = metadata.get(key)
        value = section.get(field) if isinstance(section, dict) else None
        if isinstance(value, str) and _LANGUAGE.fullmatch(value):
            return value
    return ""


def _joined(value: object) -> str:
    """Текст поля ноутбука: строка или список строк (nbformat допускает оба вида)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item for item in value if isinstance(item, str))
    return ""


def _cell_output(outputs: object) -> str:
    """Вывод ячейки: текст подряд идущих выводов — одним блоком, картинка — пометкой."""
    blocks: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        text = _terminal_text("".join(pending)).strip("\n")
        pending.clear()
        if text.strip():
            blocks.append(_fenced(_clipped(text), ""))

    for output in outputs if isinstance(outputs, list) else []:
        if not isinstance(output, dict):
            continue
        kind = output.get("output_type")
        if kind == "stream":
            pending.append(_joined(output.get("text")))
        elif kind in ("execute_result", "display_data"):
            data = output.get("data")
            data = data if isinstance(data, dict) else {}
            if any(isinstance(mime, str) and mime.startswith("image/") for mime in data):
                flush()
                blocks.append(IMAGE_MARK)
            else:
                pending.append(_line(_joined(data.get("text/plain"))))
        elif kind == "error":
            name, value = output.get("ename"), output.get("evalue")
            pending.append(_line(ERROR_LINE.format(name=_joined(name), value=_joined(value))))
    flush()
    return "\n".join(blocks)


def _line(text: str) -> str:
    """Результат ячейки — с новой строки после печати и до следующей."""
    return text if not text or text.endswith("\n") else f"{text}\n"


def _terminal_text(text: str) -> str:
    """Текст, как его видно в терминале: без цветовых кодов, а строка, которую программа
    перерисовывала через \\r (полоса прогресса), — в последнем виде."""
    text = _ANSI.sub("", text).replace("\r\n", "\n")
    return "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n"))


def _clipped(text: str) -> str:
    if len(text) <= OUTPUT_LIMIT:
        return text
    half = OUTPUT_LIMIT // 2
    skipped = f"{len(text) - 2 * half:,}".replace(",", " ")
    return f"{text[:half]}\n{OUTPUT_SKIPPED.format(skipped=skipped)}\n{text[-half:]}"


def _fenced(text: str, language: str) -> str:
    """Блок кода markdown; ограда длиннее любой серии ` внутри, чтобы блок не закрылся раньше."""
    longest = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def clean(text: str) -> str:
    """Нулевой символ Postgres не хранит, а одиночные суррогаты не записать в UTF-8."""
    return text.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


def convert(kind: str, data: bytes, options: dict[str, int]) -> Result:
    """Разбирает документ; любая ошибка разбора — итог с error, а не падение процесса."""
    try:
        if kind == "pdf":
            result = convert_pdf(data)
        elif kind == "ipynb":
            result = convert_notebook(data)
        else:
            check_archive(data, options["max_unpacked_bytes"], options["max_parts"])
            result = convert_office(kind, data)
    except Failure as failure:
        return {"error": failure.code, "error_type": "", "trace": ""}
    except MemoryError:
        # На трейсбек памяти может уже не хватить.
        return {"error": "too_complex", "error_type": "MemoryError", "trace": ""}
    except Exception as error:
        return {
            "error": "password" if _is_encrypted(error) else "broken",
            "error_type": type(error).__name__,
            "trace": "".join(traceback.format_tb(error.__traceback__)),
        }
    text = clean(result["text"])
    return result | {"text": text[: options["max_chars"]], "total": len(text)}


def _is_encrypted(error: Exception) -> bool:
    """PDF с паролем: pdfminer бросает PDFEncryptionError или её наследника."""
    return any(cls.__name__ == "PDFEncryptionError" for cls in type(error).__mro__)


def main() -> None:
    kind, options = sys.argv[1], json.loads(sys.argv[2])
    limit_memory(options["memory_mb"])
    result = convert(kind, sys.stdin.buffer.read(), options)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
