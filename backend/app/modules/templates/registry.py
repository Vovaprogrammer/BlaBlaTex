"""Реестр шаблонов: папки templates/<slug>/ с template.yaml (architecture.md 7, 9.5).

Загружается один раз при старте приложения (create_app). Проверяются все шаблоны сразу:
если хоть в одном ошибка, приложение не запускается, а TemplateError перечисляет все
проблемы — файл, поле и причину. Файлы шаблона читаются в память: шаблоны маленькие,
и при создании проекта диск уже не нужен.
"""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.modules.projects.paths import (
    OUT_DIR,
    TEXT_FILE_EXTENSIONS,
    InvalidPathError,
    is_in_out_dir,
    is_text_file_type,
    validate_path,
)
from app.modules.projects.service import TEXT_FILE_MAX_BYTES
from app.modules.templates.manifest import TemplateManifest

MANIFEST = "template.yaml"
# Пример meta.tex с вымышленным студентом: с ним шаблон собирается в CI (check-template).
SAMPLE_META = "meta.sample.tex"
# meta.tex проекта создаёт бэкенд из профиля и полей (9.6), в шаблоне его быть не должно.
META_FILE = "meta.tex"
# Эти файлы нужны только самому шаблону и в проект не копируются.
NOT_COPIED = frozenset({MANIFEST, SAMPLE_META})


@dataclass(frozen=True)
class Template:
    """Шаблон: манифест и файлы, которые копируются в новый проект (путь → текст)."""

    manifest: TemplateManifest
    files: Mapping[str, str]


# Реестр: шаблоны по slug.
Registry = Mapping[str, Template]


class TemplateError(Exception):
    """Шаблоны не прошли проверку. Текст — список проблем для автора шаблона."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Безопасный загрузчик YAML, который падает на повторяющемся ключе.

    Обычный SafeLoader молча берёт последнее значение: второй `fields:` в манифесте
    незаметно заменил бы первый.
    """

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Hashable, object]:
        # Не словарь (например, строка с тегом !!map) и ключ-список PyYAML отвергнет сам —
        # с понятной ошибкой и номером строки; здесь их только пропускаем.
        seen: set[Hashable] = set()
        for key_node, _ in node.value if isinstance(node, yaml.MappingNode) else []:
            # Ключ слияния << по правилам YAML может повторять ключи — его пропускаем.
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                repeated = key in seen
            except TypeError:
                continue
            if repeated:
                raise yaml.constructor.ConstructorError(
                    None, None, f"ключ {key} повторяется", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


# Служебные файлы Проводника Windows; .DS_Store из macOS — скрытый.
_OS_FILES = frozenset({"thumbs.db", "desktop.ini"})


def _is_ignored(name: str) -> bool:
    """Скрытые и служебные файлы ОС (.DS_Store, Thumbs.db, desktop.ini) — не часть шаблона.

    Их нет в git (.gitignore), но они бывают в папке у разработчика: из-за них бэкенд
    не должен отказываться стартовать.
    """
    return name.startswith(".") or name.casefold() in _OS_FILES


def load_templates(templates_dir: Path) -> Registry:
    """Все шаблоны папки по slug. Папки на _ (_shared, _schema) — не шаблоны.

    Пустая папка — пустой реестр. Нет папки или ошибка хоть в одном шаблоне — TemplateError.
    """
    if not templates_dir.is_dir():
        raise TemplateError(f"Нет папки шаблонов {templates_dir}")
    templates: dict[str, Template] = {}
    problems: list[str] = []
    for folder in sorted(templates_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_") or _is_ignored(folder.name):
            continue
        template = _load_template(folder, problems)
        if template is not None:
            templates[template.manifest.slug] = template
    if problems:
        lines = "\n".join(f"- {problem}" for problem in problems)
        raise TemplateError(f"Шаблоны в {templates_dir} не прошли проверку:\n{lines}")
    return templates


def _load_template(folder: Path, problems: list[str]) -> Template | None:
    """Шаблон из папки или None, если есть проблемы — они дописываются в problems."""
    where = f"{folder.name}/{MANIFEST}"
    manifest = _read_manifest(folder, problems)
    if manifest is None:
        return None
    before = len(problems)
    if manifest.slug != folder.name:
        problems.append(f"{where}: slug: {manifest.slug} не совпадает с именем папки")
    files = _read_files(folder, problems)
    required = [("main", manifest.main)] + [
        (f"sections.{index}.file", section.file) for index, section in enumerate(manifest.sections)
    ]
    for loc, path in required:
        if path not in files:
            problems.append(f"{where}: {loc}: нет файла {path}")
    if len(problems) > before:
        return None
    return Template(manifest=manifest, files=files)


def _read_manifest(folder: Path, problems: list[str]) -> TemplateManifest | None:
    path = folder / MANIFEST
    where = f"{folder.name}/{MANIFEST}"
    if not path.is_file():
        problems.append(f"{folder.name}: нет файла {MANIFEST}")
        return None
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except UnicodeDecodeError:
        problems.append(f"{where}: файл не в кодировке UTF-8")
        return None
    except yaml.YAMLError as error:
        problems.append(f"{where}: {_yaml_problem(error)}")
        return None
    try:
        return TemplateManifest.model_validate(data)
    except ValidationError as error:
        for detail in error.errors():
            loc = ".".join(str(part) for part in detail["loc"])
            # Текст ValueError из валидаторов модели Pydantic начинает с «Value error, ».
            message = detail["msg"].removeprefix("Value error, ")
            problems.append(f"{where}: {loc}: {message}" if loc else f"{where}: {message}")
        return None


def _yaml_problem(error: yaml.YAMLError) -> str:
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark is not None:
        # Строки в отметке PyYAML считаются с нуля.
        return f"строка {error.problem_mark.line + 1}: {error.problem}"
    return str(error)


def _read_files(folder: Path, problems: list[str]) -> dict[str, str]:
    """Файлы шаблона, которые копируются в проект: путь → текст.

    Каждый файл должен стать обычным текстовым файлом проекта (9.8): путь по правилам,
    тип из текстовых, UTF-8 до 2 МБ.
    """
    files: dict[str, str] = {}
    root = folder.resolve()
    for file in sorted(folder.rglob("*")):
        relative = file.relative_to(folder).as_posix()
        if file.is_dir() or relative in NOT_COPIED:
            continue
        if any(_is_ignored(part) for part in relative.split("/")):
            continue
        where = f"{folder.name}/{relative}"
        # Ссылка на файл вне шаблона попала бы в каждый проект студента.
        if not file.resolve().is_relative_to(root):
            problems.append(f"{where}: ссылка ведёт за пределы папки шаблона")
            continue
        try:
            path = validate_path(relative)
        except InvalidPathError as error:
            problems.append(f"{where}: {error}")
            continue
        problem = _file_problem(path)
        if problem is not None:
            problems.append(f"{where}: {problem}")
            continue
        # Размер — до чтения: случайно попавший большой файл не читается в память целиком.
        if file.stat().st_size > TEXT_FILE_MAX_BYTES:
            problems.append(f"{where}: текстовый файл больше 2 МБ")
            continue
        data = file.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{where}: файл не в кодировке UTF-8")
            continue
        if "\x00" in text:
            problems.append(f"{where}: в тексте нулевой символ")
            continue
        # git на Windows может выдать файлы с CRLF; в проекте они одинаковые на любой машине.
        files[path] = text.replace("\r\n", "\n")
    return files


def _file_problem(path: str) -> str | None:
    """Почему файл с проверенным путём нельзя скопировать в проект, или None."""
    if path == META_FILE:
        return f"{META_FILE} создаёт бэкенд из профиля и полей (9.6); пример — в {SAMPLE_META}"
    if is_in_out_dir(path):
        return f"папка {OUT_DIR}/ занята: туда сборка пишет результаты (9.7)"
    if not is_text_file_type(path):
        # Бинарные файлы проект пока не хранит — они появятся с загрузкой файлов (B2.2).
        return f"шаблон может содержать только текстовые файлы: {' '.join(TEXT_FILE_EXTENSIONS)}"
    return None
