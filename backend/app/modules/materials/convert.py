"""Разбор документа в отдельном процессе (architecture.md 5). Запускает его materials/extraction.py.

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


def clean(text: str) -> str:
    """Нулевой символ Postgres не хранит, а одиночные суррогаты не записать в UTF-8."""
    return text.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


def convert(kind: str, data: bytes, options: dict[str, int]) -> Result:
    """Разбирает документ; любая ошибка разбора — итог с error, а не падение процесса."""
    try:
        if kind == "pdf":
            result = convert_pdf(data)
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
