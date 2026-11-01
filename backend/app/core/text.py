"""Строки из запросов, которые сохраняются в Postgres."""

from pydantic import AfterValidator
from pydantic_core import PydanticCustomError


def reject_nul(value: str) -> str:
    """Нулевой символ — ошибка поля. Postgres не хранит его ни в text, ни в jsonb,
    и без проверки запрос падал бы на базе с ответом 500."""
    if "\x00" in value:
        raise PydanticCustomError("nul_character", "Text must not contain NUL")
    return value


# Для Annotated[str, ..., NoNul]: так помечается каждое строковое поле, которое уходит в базу.
NoNul = AfterValidator(reject_nul)
