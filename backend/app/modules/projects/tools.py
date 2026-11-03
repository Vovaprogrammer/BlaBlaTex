"""ProjectTools — действия агента над проектом (architecture.md 9.4).

Здесь только договор: протокол, контекст, ошибки и типы результатов, а ещё общие правила,
по которым любая реализация нумерует строки, ищет и заменяет текст. Настоящая реализация
поверх сервисов — B2.5, фейк для тестов — tests/fake_project_tools.py. Обе пользуются
функциями ниже: агент на фейке видит тот же текст, что на настоящем проекте.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from app.modules.builds.schemas import BuildError
from app.modules.profiles.schemas import ProfileOut
from app.modules.projects.schemas import FileInfo
from app.modules.templates.schemas import TemplateSection

DEFAULT_MAX_RESULTS = 50
DEFAULT_MATERIAL_LIMIT = 20_000
SNIPPET_MAX_CHARS = 200
# Сколько символов строки показать до найденного, если строка длиннее SNIPPET_MAX_CHARS.
_SNIPPET_LEAD = 50
# Картинки, которые можно показать модели. SVG модели обычно не принимают.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

Actor = Literal["user", "ai", "mcp"]
MaterialStatus = Literal["pending", "ready", "failed"]


@dataclass(frozen=True)
class ToolContext:
    """Кто действует и в каком проекте. Реализация ProjectTools получает его при создании."""

    project_id: UUID
    user_id: UUID
    actor: Actor
    # Все записи попадают в этот changeset (B2.5).
    changeset_id: UUID | None


class ToolErrorCode(StrEnum):
    """Коды ToolError (9.4). Где ошибка та же, что в REST, код совпадает с ErrorCode (9.2)."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    FORBIDDEN = "forbidden"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    INVALID_PATH = "invalid_path"
    VALIDATION_ERROR = "validation_error"
    PROJECT_LOCKED = "project_locked"
    EDIT_NOT_FOUND = "edit_not_found"
    EDIT_NOT_UNIQUE = "edit_not_unique"
    MATERIAL_NOT_READY = "material_not_ready"
    INTERNAL = "internal"


class ToolError(Exception):
    """Ошибка, которую модель может исправить или объяснить пользователю.

    message отдаётся модели как результат инструмента, поэтому он на русском и понятный.
    В details — данные для программы агента, например число вхождений у edit_not_unique.
    """

    def __init__(
        self,
        code: ToolErrorCode,
        message: str,
        details: Mapping[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, JsonValue] = dict(details or {})


class FileText(BaseModel):
    """Кусок текстового файла с номерами строк."""

    path: str
    version: int
    text: str = Field(description="Строки «номер, табуляция, текст» через \\n")
    start_line: int
    end_line: int = Field(description="Последняя строка куска; меньше start_line, если строк нет")
    total_lines: int


class SearchHit(BaseModel):
    path: str
    line: int
    snippet: str = Field(description=f"Кусок строки до {SNIPPET_MAX_CHARS} символов с найденным")


class EditResult(BaseModel):
    file: FileInfo
    line: int = Field(description="Строка, с которой началась замена")


class BuildResult(BaseModel):
    """Итог сборки для агента: как BuildOut, но сборка уже закончилась."""

    status: Literal["ok", "error", "timeout"]
    build_id: UUID
    pages: int | None
    errors: list[BuildError] = Field(description="Ошибки и предупреждения (severity)")
    warnings_count: int


class MaterialInfo(BaseModel):
    path: str
    mime: str | None
    size: int = Field(description="Размер в байтах")
    status: MaterialStatus = Field(description="Извлечение текста (B2.7)")
    description: str | None = Field(description="Описание картинки или null")


class MaterialText(BaseModel):
    text: str
    offset: int
    total: int = Field(description="Длина всего извлечённого текста в символах")


class ImageData(BaseModel):
    # Картинка бывает до 20 МБ: байты не попадают ни в repr, ни в логи.
    data: bytes = Field(repr=False)
    mime: str


class GuideField(BaseModel):
    """Поле проекта: значение и макрос, через который оно попадает в отчёт (9.6)."""

    key: str
    label: str
    value: str | int | None
    macro: str = Field(description="Например, \\bbtLabNumber")


class TemplateMacro(BaseModel):
    """Макрос класса из 9.6."""

    usage: str = Field(
        description="Как вызвать, например \\bbtScreenshot[width]{path}{caption}{label}"
    )
    description: str


class TemplateGuide(BaseModel):
    """Что агенту нужно знать о шаблоне проекта."""

    slug: str
    title: str
    discipline: str | None
    main_file: str
    sections: list[TemplateSection]
    ai_rules: str
    fields: list[GuideField]
    macros: list[TemplateMacro]


@runtime_checkable
class ProjectTools(Protocol):
    """Действия агента над одним проектом (9.4).

    Пути — по 9.8, файлы role=generated не меняются (9.6). Ошибка, которую модель может
    исправить, — ToolError; остальные исключения выходят наружу и завершают прогон.
    """

    async def list_files(self) -> list[FileInfo]:
        """Все файлы и папки проекта."""
        ...

    async def read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> FileText:
        """Текстовый файл целиком или строки с start_line по end_line включительно."""
        ...

    async def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchHit]:
        """Строки текстовых файлов с query без учёта регистра, по пути и номеру строки."""
        ...

    async def write_file(self, path: str, content: str) -> FileInfo:
        """Создаёт или перезаписывает текстовый файл; папки над ним создаются сами."""
        ...

    async def edit_file(self, path: str, old: str, new: str) -> EditResult:
        """Заменяет единственное вхождение old на new."""
        ...

    async def delete_file(self, path: str) -> None:
        """Удаляет файл или папку со всем содержимым."""
        ...

    async def compile(self) -> BuildResult:
        """Собирает проект и ждёт итог."""
        ...

    async def list_materials(self) -> list[MaterialInfo]:
        """Файлы из materials/ и состояние извлечения текста."""
        ...

    async def read_material(
        self, path: str, offset: int = 0, limit: int = DEFAULT_MATERIAL_LIMIT
    ) -> MaterialText:
        """Кусок извлечённого текста материала: не больше limit символов с offset."""
        ...

    async def get_image(self, path: str) -> ImageData:
        """Картинка .png, .jpg или .jpeg."""
        ...

    async def get_template_guide(self) -> TemplateGuide:
        """Разделы, правила и поля шаблона проекта, макросы класса."""
        ...

    async def get_profile(self) -> ProfileOut:
        """Профиль студента, как GET /profile."""
        ...


def invalid_argument(message: str) -> ToolError:
    return ToolError(ToolErrorCode.VALIDATION_ERROR, message)


def not_text_file(path: str) -> ToolError:
    """read_file у файла, который хранится не текстом: картинки, документы."""
    return ToolError(
        ToolErrorCode.UNSUPPORTED_FILE_TYPE,
        f"Файл {path} не текстовый, построчно его не прочитать. "
        "Картинки и материалы открываются отдельными инструментами.",
    )


def split_lines(content: str) -> list[str]:
    """Строки файла так, как их нумерует read_file: только по \\n.

    Завершающий \\n не даёт лишней пустой строки, у пустого файла строк нет.
    """
    if not content:
        return []
    return content.removesuffix("\n").split("\n")


def read_lines(
    path: str,
    version: int,
    content: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> FileText:
    """FileText для read_file: строки с start_line по end_line, диапазон за концом обрезается."""
    lines = split_lines(content)
    start = 1 if start_line is None else start_line
    if start < 1:
        raise invalid_argument("Строки нумеруются с 1")
    if end_line is not None and end_line < start:
        raise invalid_argument("Конец диапазона строк раньше начала")
    end = len(lines) if end_line is None else min(end_line, len(lines))
    text = "\n".join(f"{number}\t{lines[number - 1]}" for number in range(start, end + 1))
    return FileText(
        path=path,
        version=version,
        text=text,
        start_line=start,
        end_line=end,
        total_lines=len(lines),
    )


def count_occurrences(text: str, fragment: str) -> int:
    """Сколько раз fragment встречается в text, с перекрытиями: в «ааа» «аа» — 2 раза.

    С перекрытиями — потому что и тогда непонятно, какое из вхождений заменять.
    """
    count, position = 0, text.find(fragment)
    while position != -1:
        count += 1
        position = text.find(fragment, position + 1)
    return count


def replace_once(content: str, old: str, new: str) -> tuple[str, int]:
    """Заменяет единственное вхождение old на new для edit_file.

    Возвращает новый текст и номер строки, с которой началась замена. Нет вхождений —
    edit_not_found, больше одного — edit_not_unique с числом в details.count.
    """
    if not old:
        raise invalid_argument("Укажите фрагмент, который нужно заменить")
    count = count_occurrences(content, old)
    if count == 0:
        raise ToolError(
            ToolErrorCode.EDIT_NOT_FOUND,
            "Фрагмент не найден. Перечитайте файл: фрагмент должен совпадать до символа "
            "и без номеров строк.",
        )
    if count > 1:
        raise ToolError(
            ToolErrorCode.EDIT_NOT_UNIQUE,
            f"Фрагмент найден несколько раз: {count}. Добавьте соседние строки, "
            "чтобы он встречался один раз.",
            {"count": count},
        )
    position = content.find(old)
    line = content.count("\n", 0, position) + 1
    return content[:position] + new + content[position + len(old) :], line


def check_search(query: str, max_results: int) -> None:
    """Аргументы search: запрос не пустой, результатов хотя бы один."""
    if not query:
        raise invalid_argument("Укажите, что искать")
    if max_results < 1:
        raise invalid_argument("Число результатов должно быть не меньше 1")


def find_lines(path: str, content: str, query: str) -> Iterator[SearchHit]:
    """Строки файла с query без учёта регистра, по порядку.

    В длинной строке snippet — кусок вокруг первого вхождения, а не начало строки:
    абзац LaTeX часто занимает одну строку в тысячу символов.
    """
    needle = query.lower()
    for number, line in enumerate(split_lines(content), start=1):
        position = line.lower().find(needle)
        if position == -1:
            continue
        start = max(0, min(position - _SNIPPET_LEAD, len(line) - SNIPPET_MAX_CHARS))
        yield SearchHit(path=path, line=number, snippet=line[start : start + SNIPPET_MAX_CHARS])


def material_slice(text: str, offset: int, limit: int) -> MaterialText:
    """Кусок извлечённого текста для read_material; offset за концом — пустой кусок."""
    if offset < 0:
        raise invalid_argument("offset не может быть отрицательным")
    if limit < 1:
        raise invalid_argument("limit должен быть не меньше 1")
    return MaterialText(text=text[offset : offset + limit], offset=offset, total=len(text))


def check_image(path: str) -> None:
    """get_image показывает только .png, .jpg и .jpeg, регистр расширения не важен."""
    if PurePosixPath(path).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ToolError(
            ToolErrorCode.UNSUPPORTED_FILE_TYPE,
            f"Файл {path} не показать как картинку. Подходят: {' '.join(IMAGE_EXTENSIONS)}",
        )
