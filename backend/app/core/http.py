"""Общие заголовки HTTP-ответов."""

from urllib.parse import quote

# Не ASCII или эти символы — в запасном имени _: кавычка и \ ломают строку в кавычках,
# а % старые браузеры раскодируют как %XX.
_FALLBACK_UNSAFE = frozenset('"\\%')


def content_disposition(filename: str, *, attachment: bool = False) -> str:
    """Content-Disposition: inline — открыть в браузере, attachment — скачать, и имя файла
    для «Сохранить как».

    Русское имя — в filename* (RFC 6266, кодировка по RFC 5987). В filename — для старых
    клиентов — то же имя, где символы не из ASCII, кавычки, \\ и % заменены на _.
    """
    disposition = "attachment" if attachment else "inline"
    fallback = "".join(
        char if char.isascii() and char.isprintable() and char not in _FALLBACK_UNSAFE else "_"
        for char in filename
    )
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
