"""ProjectTools в памяти для тестов агента (architecture.md 9.4): без БД, Redis и воркера.

Фейк ведёт себя как сервис файлов: пути проверяет validate_path, типы файлов и лимиты —
те же, что в 9.8, файлы role=generated (meta.tex) и папки с ними не меняются (9.6).
Нумерацию строк, замену и поиск он берёт из projects/tools.py, как и настоящая реализация.
Что фейк ведёт себя как настоящая ProjectTools, проверяют общие тесты
tests/project_tools_contract.py.

    tools = FakeProjectTools(
        {"main.tex": MAIN},
        generated={"meta.tex": META},
        builds=[build_error(latex_error("Undefined control sequence", line=3)), build_ok()],
    )
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal

from app.modules.builds.schemas import BuildError
from app.modules.profiles.schemas import ProfileOut
from app.modules.projects import service as projects_service
from app.modules.projects.paths import (
    BINARY_FILE_TYPES,
    TEXT_FILE_EXTENSIONS,
    InvalidPathError,
    is_text_file_type,
    validate_path,
)
from app.modules.projects.schemas import FileInfo, FileKind, FileRole
from app.modules.projects.service import (
    FILE_NOT_FOUND_MESSAGE,
    GENERATED_FILE_MESSAGE,
    PATH_NOT_FOUND_MESSAGE,
    TEXT_MIME,
)
from app.modules.projects.tools import (
    DEFAULT_MATERIAL_LIMIT,
    DEFAULT_MAX_RESULTS,
    BuildResult,
    EditResult,
    FileText,
    GuideField,
    ImageData,
    MaterialInfo,
    MaterialStatus,
    MaterialText,
    SearchHit,
    TemplateGuide,
    TemplateMacro,
    ToolError,
    ToolErrorCode,
    check_image,
    material_slice,
    not_text_file,
    read_lines,
    replace_once,
    search_texts,
)
from app.modules.templates.schemas import TemplateSection

MATERIALS_DIR = "materials/"

# Шаблон и профиль по умолчанию: вымышленная лабораторная и вымышленный студент.
DEFAULT_GUIDE = TemplateGuide(
    slug="test-lab",
    title="Лабораторная работа",
    discipline="Структуры и алгоритмы обработки данных",
    main_file="main.tex",
    sections=[
        TemplateSection(
            id="goal",
            title="Цель работы",
            file="sections/goal.tex",
            required=True,
            guide="1–2 предложения из методички.",
        ),
        TemplateSection(
            id="progress",
            title="Ход работы",
            file="sections/progress.tex",
            required=True,
            guide="По заданиям: что сделано, код, скриншот результата.",
        ),
    ],
    ai_rules="Факты — только из материалов.",
    fields=[GuideField(key="lab_number", label="Номер работы", value=1, macro="\\bbtLabNumber")],
    macros=[
        TemplateMacro(
            usage="\\bbtScreenshot[width]{path}{caption}{label}",
            description="Рисунок «Рисунок N — caption»",
        )
    ],
)
DEFAULT_PROFILE = ProfileOut(
    last_name="Иванов",
    first_name="Иван",
    middle_name="Иванович",
    group_name="БВТ0000",
    faculty="Информационные технологии",
    department="Математическая кибернетика",
    updated_at=datetime(2026, 9, 1, tzinfo=UTC),
)


def latex_error(
    message: str, *, file: str | None = "main.tex", line: int | None = 1, context: str = ""
) -> BuildError:
    """Ошибка LaTeX для сценария сборки."""
    return BuildError(file=file, line=line, message=message, context=context, severity="error")


def build_ok(pages: int = 1) -> BuildResult:
    return BuildResult(status="ok", build_id=uuid.uuid4(), pages=pages, errors=[], warnings_count=0)


def build_error(*errors: BuildError, status: Literal["error", "timeout"] = "error") -> BuildResult:
    """Неудачная сборка; errors — ошибки и предупреждения, как в BuildResult."""
    return BuildResult(
        status=status,
        build_id=uuid.uuid4(),
        pages=None,
        errors=list(errors),
        warnings_count=sum(error.severity == "warning" for error in errors),
    )


# Сценарий сборки: итоги по очереди (последний повторяется) или функция от фейка —
# например, ошибка, пока в main.tex нет \end{document}.
type CompileScenario = Sequence[BuildResult] | Callable[[FakeProjectTools], BuildResult]


@dataclass(frozen=True)
class FakeMaterial:
    """Файл в materials/ и итог извлечения его текста (B2.7). Текст в content — код."""

    content: str | bytes
    text: str = ""
    status: MaterialStatus = "ready"
    description: str | None = None


@dataclass
class _Entry:
    kind: FileKind
    role: FileRole
    version: int
    updated_at: datetime
    size: int = 0
    text: str | None = None
    data: bytes | None = None
    mime: str | None = None


class FakeProjectTools:
    """Проект в памяти. Тест задаёт файлы, материалы и сценарий сборки, а потом смотрит
    содержимое (content) и вызванные действия (calls). locked = True — проект занят
    другим прогоном: изменения отвечают project_locked."""

    def __init__(
        self,
        files: Mapping[str, str] | None = None,
        *,
        generated: Mapping[str, str] | None = None,
        binary: Mapping[str, bytes] | None = None,
        materials: Mapping[str, FakeMaterial] | None = None,
        builds: CompileScenario = (),
        guide: TemplateGuide | None = None,
        profile: ProfileOut | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.locked = False
        self._entries: dict[str, _Entry] = {}
        self._materials: dict[str, FakeMaterial] = {}
        self._last_version = 0
        self._builds = builds
        # Свой счётчик, а не calls: тест может очистить calls между шагами.
        self._compiles = 0
        self._guide = guide or DEFAULT_GUIDE
        self._profile = profile or DEFAULT_PROFILE
        for path, text in (files or {}).items():
            self._add_text(path, text, "source")
        for path, text in (generated or {}).items():
            self._add_text(path, text, "generated")
        for path, data in (binary or {}).items():
            self._add_binary(path, data, "source")
        for path, material in (materials or {}).items():
            if not path.startswith(MATERIALS_DIR):
                raise ValueError(f"Материал {path} должен лежать в {MATERIALS_DIR}")
            if isinstance(material.content, str):
                self._add_text(path, material.content, "material")
            else:
                self._add_binary(path, material.content, "material")
            self._materials[validate_path(path)] = material

    def content(self, path: str) -> str:
        """Текст файла как есть — для проверок в тестах."""
        text = self._entries[validate_path(path)].text
        if text is None:
            raise KeyError(path)
        return text

    async def list_files(self) -> list[FileInfo]:
        self.calls.append("list_files")
        return [_info(path, entry) for path, entry in sorted(self._entries.items())]

    async def read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> FileText:
        self.calls.append("read_file")
        path = _valid(path)
        entry, text = self._text(path)
        return read_lines(path, entry.version, text, start_line, end_line)

    async def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchHit]:
        self.calls.append("search")
        texts = [
            (path, entry.text) for path, entry in self._entries.items() if entry.text is not None
        ]
        return search_texts(texts, query, max_results)

    async def write_file(self, path: str, content: str) -> FileInfo:
        """Порядок проверок — как у записи файла в сервисе (write_text_file)."""
        self.calls.append("write_file")
        path = _valid(path)
        size = _check_text(content)
        self._check_unlocked()
        entry = self._entries.get(path)
        if entry is not None and entry.kind != "text":
            raise ToolError(ToolErrorCode.ALREADY_EXISTS, "По этому пути уже есть папка или файл")
        if entry is not None and entry.role == "generated":
            raise _generated_file()
        _check_text_type(path)
        self._check_project_size(size - (entry.size if entry else 0))
        if entry is None:
            entry = self._add(path, _Entry("text", "source", 0, _now(), mime=TEXT_MIME))
        self._set_text(entry, content, size)
        return _info(path, entry)

    async def edit_file(self, path: str, old: str, new: str) -> EditResult:
        self.calls.append("edit_file")
        path = _valid(path)
        self._check_unlocked()
        entry, text = self._text(path)
        if entry.role == "generated":
            raise _generated_file()
        content, line = replace_once(text, old, new)
        size = _check_text(content)
        self._check_project_size(size - entry.size)
        self._set_text(entry, content, size)
        return EditResult(file=_info(path, entry), line=line)

    async def delete_file(self, path: str) -> None:
        self.calls.append("delete_file")
        path = _valid(path)
        self._check_unlocked()
        entry = self._entries.get(path)
        if entry is None:
            raise ToolError(ToolErrorCode.NOT_FOUND, PATH_NOT_FOUND_MESSAGE)
        if entry.role == "generated":
            raise _generated_file()
        inside = sorted(other for other in self._entries if other.startswith(f"{path}/"))
        for other in inside:
            if self._entries[other].role == "generated":
                raise ToolError(
                    ToolErrorCode.FORBIDDEN,
                    f"В папке есть файл {other}, он создаётся автоматически",
                )
        for removed in [path, *inside]:
            del self._entries[removed]
            self._materials.pop(removed, None)

    async def compile(self) -> BuildResult:
        self.calls.append("compile")
        self._compiles += 1
        if callable(self._builds):
            return self._builds(self)
        if not self._builds:
            return build_ok()
        return self._builds[min(self._compiles, len(self._builds)) - 1]

    async def list_materials(self) -> list[MaterialInfo]:
        self.calls.append("list_materials")
        return [
            MaterialInfo(
                path=path,
                mime=self._entries[path].mime,
                size=self._entries[path].size,
                status=material.status,
                description=material.description,
            )
            for path, material in sorted(self._materials.items())
        ]

    async def read_material(
        self, path: str, offset: int = 0, limit: int = DEFAULT_MATERIAL_LIMIT
    ) -> MaterialText:
        self.calls.append("read_material")
        material = self._materials.get(_valid(path))
        if material is None:
            raise ToolError(ToolErrorCode.NOT_FOUND, "Материал не найден")
        if material.status == "pending":
            raise ToolError(
                ToolErrorCode.MATERIAL_NOT_READY,
                "Текст материала ещё извлекается, попробуйте позже",
            )
        if material.status == "failed":
            raise ToolError(
                ToolErrorCode.MATERIAL_NOT_READY, "Текст из материала извлечь не удалось"
            )
        return material_slice(material.text, offset, limit)

    async def get_image(self, path: str) -> ImageData:
        self.calls.append("get_image")
        path = _valid(path)
        entry = self._entries.get(path)
        if entry is None or entry.kind == "folder":
            raise ToolError(ToolErrorCode.NOT_FOUND, FILE_NOT_FOUND_MESSAGE)
        check_image(path)
        # .png и .jpg текстом не сохранить, поэтому у картинки всегда есть байты.
        assert entry.data is not None and entry.mime is not None
        return ImageData(data=entry.data, mime=entry.mime)

    # Копии: правка результата в одном тесте не должна менять данные по умолчанию в других.
    async def get_template_guide(self) -> TemplateGuide:
        self.calls.append("get_template_guide")
        return self._guide.model_copy(deep=True)

    async def get_profile(self) -> ProfileOut:
        self.calls.append("get_profile")
        return self._profile.model_copy(deep=True)

    def _check_unlocked(self) -> None:
        if self.locked:
            raise ToolError(ToolErrorCode.PROJECT_LOCKED, "Проект занят: идёт другой прогон")

    def _text(self, path: str) -> tuple[_Entry, str]:
        """Текстовый файл. Нет его или это папка — not_found, не текст — unsupported_file_type."""
        entry = self._entries.get(path)
        if entry is None or entry.kind == "folder":
            raise ToolError(ToolErrorCode.NOT_FOUND, FILE_NOT_FOUND_MESSAGE)
        if entry.text is None:
            raise not_text_file(path)
        return entry, entry.text

    def _check_project_size(self, added: int) -> None:
        used = sum(entry.size for entry in self._entries.values())
        # Лимит читается из сервиса при каждом вызове: тест может его подменить.
        limit = projects_service.PROJECT_MAX_BYTES
        if used + added > limit:
            raise ToolError(
                ToolErrorCode.PAYLOAD_TOO_LARGE,
                f"Проект не может быть больше {limit // (1024 * 1024)} МБ. Удалите ненужные файлы.",
            )

    def _set_text(self, entry: _Entry, content: str, size: int) -> None:
        self._last_version += 1
        entry.text, entry.size = content, size
        entry.version, entry.updated_at = self._last_version, _now()

    def _add(self, path: str, entry: _Entry) -> _Entry:
        """Кладёт новый файл, создав папки над ним. На месте папки файл — already_exists."""
        parents = _parents(path)
        for parent in parents:
            existing = self._entries.get(parent)
            if existing is not None and existing.kind != "folder":
                raise ToolError(
                    ToolErrorCode.ALREADY_EXISTS, f"На месте папки {parent} уже есть файл"
                )
        for parent in parents:
            self._entries.setdefault(parent, _Entry("folder", "source", 1, _now()))
        self._entries[path] = entry
        return entry

    def _add_text(self, path: str, content: str, role: FileRole) -> None:
        """Файл проекта при создании фейка — с теми же проверками, что запись."""
        path = _valid(path)
        if path in self._entries:
            raise ValueError(f"Файл {path} задан дважды")
        size = _check_text(content)
        _check_text_type(path)
        self._check_project_size(size)
        entry = self._add(path, _Entry("text", role, 0, _now(), mime=TEXT_MIME))
        self._set_text(entry, content, size)

    def _add_binary(self, path: str, data: bytes, role: FileRole) -> None:
        """Картинка или документ: только типы 9.8, которые хранятся не текстом."""
        path = _valid(path)
        if path in self._entries:
            raise ValueError(f"Файл {path} задан дважды")
        mime = BINARY_FILE_TYPES.get(PurePosixPath(path).suffix.lower())
        if mime is None:
            raise ValueError(f"Файл {path} не загрузить: подходят {' '.join(BINARY_FILE_TYPES)}")
        self._check_project_size(len(data))
        self._last_version += 1
        self._add(
            path,
            _Entry("binary", role, self._last_version, _now(), len(data), data=data, mime=mime),
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _valid(path: str) -> str:
    try:
        return validate_path(path)
    except InvalidPathError as error:
        raise ToolError(ToolErrorCode.INVALID_PATH, str(error)) from None


def _check_text(content: str) -> int:
    """Размер текста в байтах UTF-8; больше лимита или с нулевым символом — ToolError."""
    size = len(content.encode())
    if size > projects_service.TEXT_FILE_MAX_BYTES:
        raise ToolError(ToolErrorCode.PAYLOAD_TOO_LARGE, projects_service.file_too_large().message)
    if "\x00" in content:
        raise ToolError(ToolErrorCode.VALIDATION_ERROR, "В тексте не может быть нулевого символа")
    return size


def _check_text_type(path: str) -> None:
    if not is_text_file_type(path):
        raise ToolError(
            ToolErrorCode.UNSUPPORTED_FILE_TYPE,
            f"Файл {path} не сохранить текстом. Подходят: {' '.join(TEXT_FILE_EXTENSIONS)}",
        )


def _generated_file() -> ToolError:
    return ToolError(ToolErrorCode.FORBIDDEN, GENERATED_FILE_MESSAGE)


def _parents(path: str) -> list[str]:
    """Папки над путём, от верхней: a/b/c.tex → [a, a/b]."""
    parts = path.split("/")[:-1]
    return ["/".join(parts[: index + 1]) for index in range(len(parts))]


def _info(path: str, entry: _Entry) -> FileInfo:
    return FileInfo(
        path=path,
        kind=entry.kind,
        role=entry.role,
        mime=entry.mime,
        size=entry.size,
        version=entry.version,
        updated_at=entry.updated_at,
    )
