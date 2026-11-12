"""Постраничная выдача списков (architecture.md 9.1, «Списки»).

Страницами отдаются только длинные списки, которые растут без предела: история правок и
чат. Следующая страница — before=<id самой старой полученной записи>, has_more — есть ли
ещё. Границы limit у всех таких списков одни и те же.
"""

from collections.abc import Sequence
from typing import Annotated

from fastapi import Query

PAGE_DEFAULT_LIMIT = 50
PAGE_MAX_LIMIT = 100

PageLimit = Annotated[
    int,
    Query(ge=1, le=PAGE_MAX_LIMIT, description=f"Сколько записей на странице: 1–{PAGE_MAX_LIMIT}"),
]


def split_page[T](rows: Sequence[T], limit: int) -> tuple[list[T], bool]:
    """Страница из limit записей и есть ли ещё. Запрос берёт limit + 1 строку: лишняя
    строка значит, что записи есть и дальше."""
    return list(rows[:limit]), len(rows) > limit
