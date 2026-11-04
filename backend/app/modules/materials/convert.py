"""Разбор документа в отдельном процессе (architecture.md 5). Запускает его materials/extraction.py.

`python -I -X utf8 convert.py <kind> <memory_mb>`: файл приходит в stdin, итог — JSON в stdout.
Файлы чужие и непроверенные, поэтому разбор — не в процессе воркера: здесь нет ни секретов
в окружении, ни соединений с базой, память ограничена, а родитель убивает процесс по сроку.
Модуль ничего не импортирует из app: его запускают как отдельный скрипт.

Итог: {"text", "pages", "method"} или {"error", "error_type", "trace"}. В trace — только
где упал разбор, без текста исключения: в нём может оказаться кусок файла.
"""

import io
import json
import re
import sys
import traceback
from typing import Any

PAGE_MARKER = "<!-- Страница {} -->"
# Так markitdown отмечает начало каждого слайда.
SLIDE_MARKER = re.compile(r"^<!-- Slide number: \d+ -->$", re.MULTILINE)

# Any: итог уходит в JSON, его проверяет родитель (extraction.ConverterOutput).
Result = dict[str, Any]


def limit_memory(memory_mb: int) -> None:
    """Лимит памяти процесса. Он есть на Linux (прод и CI); на Windows (dev) — без лимита."""
    try:
        import resource
    except ImportError:
        return
    limit = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def convert_pdf(data: bytes) -> Result:
    """Текст PDF по страницам: перед каждой — маркер с номером."""
    from pdfminer.high_level import extract_text

    pages = extract_text(io.BytesIO(data)).split("\f")
    # pdfminer ставит \f после каждой страницы, поэтому за последним \f — пустой хвост.
    if pages[-1].strip() == "":
        pages.pop()
    text = "\n\n".join(
        f"{PAGE_MARKER.format(number)}\n{page.strip()}".rstrip()
        for number, page in enumerate(pages, start=1)
    )
    return {"text": text, "pages": len(pages), "method": "pdfminer"}


def convert_office(kind: str, data: bytes) -> Result:
    """docx, pptx и xlsx — в markdown через markitdown. У презентации pages — число слайдов."""
    from markitdown import StreamInfo
    from markitdown.converters import DocxConverter, PptxConverter, XlsxConverter

    converters = {"docx": DocxConverter, "pptx": PptxConverter, "xlsx": XlsxConverter}
    result = converters[kind]().convert(io.BytesIO(data), StreamInfo(extension=f".{kind}"))
    text = result.markdown
    pages = len(SLIDE_MARKER.findall(text)) if kind == "pptx" else None
    return {"text": text, "pages": pages, "method": "markitdown"}


def convert(kind: str, data: bytes) -> Result:
    """Разбирает документ; любая ошибка разбора — итог с error, а не падение процесса."""
    try:
        return convert_pdf(data) if kind == "pdf" else convert_office(kind, data)
    except Exception as error:
        return {
            "error": "broken",
            "error_type": type(error).__name__,
            "trace": "".join(traceback.format_tb(error.__traceback__)),
        }


def main() -> None:
    kind, memory_mb = sys.argv[1], int(sys.argv[2])
    limit_memory(memory_mb)
    result = convert(kind, sys.stdin.buffer.read())
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
