"""Манифест шаблона template.yaml (architecture.md 9.5): модель и её проверки.

Из модели генерируется JSON Schema для авторов шаблонов (app/scripts/export_template_schema.py).
Описания полей попадают в схему — редактор показывает их подсказками, поэтому они на русском.
Проверки, которых нет в JSON Schema (уникальность ключей, options у select, тип default),
делают валидаторы модели. Файлы шаблона на диске проверяет реестр.
"""

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationInfo,
    field_validator,
)

from app.modules.projects.schemas import (
    FIELD_VALUE_MAX_LENGTH,
    TEMPLATE_SLUG_MAX_LENGTH,
    Engine,
    FilePath,
    ProjectKind,
)
from app.modules.templates.schemas import FieldType

# Длина значения поля (9.5): у string и select — как у полей профиля, у text — общий
# предел схемы запроса. У int длины нет.
FIELD_STRING_MAX_LENGTH = 200
MAX_VALUE_LENGTH: dict[FieldType, int] = {
    "string": FIELD_STRING_MAX_LENGTH,
    "select": FIELD_STRING_MAX_LENGTH,
    "text": FIELD_VALUE_MAX_LENGTH,
}

# Макросы 9.6, которые задают meta.tex и класс. Поле с таким ключом их бы перезаписало.
RESERVED_MACROS = frozenset(
    {
        "LastName", "FirstName", "MiddleName", "ShortName", "FullName",
        "Group", "Faculty", "Department", "Discipline", "Year", "City",
        "TitlePage", "Screenshot", "CodeFile",
    }
)  # fmt: skip

# Опечатка в ключе — ошибка, а не молча пропущенное поле. Strict: "3" не становится числом 3,
# а yes из YAML — строкой.
_CONFIG = ConfigDict(extra="forbid", strict=True)


def macro_suffix(key: str) -> str:
    """Часть имени макроса поля после \\bbt: lab_number → LabNumber (9.6)."""
    return "".join(part.capitalize() for part in key.split("_"))


def _free_key(key: str) -> str:
    if macro_suffix(key) in RESERVED_MACROS:
        raise ValueError(f"ключ даёт макрос \\bbt{macro_suffix(key)} из 9.6 — он занят")
    return key


# Хотя бы один непробельный символ: подпись из одних пробелов в форме не видна.
NonEmptyText = Annotated[str, Field(min_length=1, pattern=r"\S")]
# Только буквы и _: в имени макроса TeX цифры недопустимы — \bbtLab2 читается как \bbtLab и «2».
FieldKey = Annotated[
    str,
    Field(
        pattern=r"^[a-z]+(_[a-z]+)*$",
        max_length=50,
        description=(
            "Слова из строчных латинских букв через одиночный _, например lab_number → "
            "макрос \\bbtLabNumber"
        ),
    ),
    AfterValidator(_free_key),
]
# Строковый default — до предела для любого поля; лимит по типу проверяет _default_matches_type.
DefaultText = Annotated[StrictStr, Field(max_length=FIELD_VALUE_MAX_LENGTH)]
# FilePath — правила путей 9.8, как у файлов проекта: файлы шаблона копируются в проект.
TexFile = Annotated[
    FilePath,
    Field(
        pattern=r"\.tex$", description="Путь .tex внутри папки шаблона, например sections/goal.tex"
    ),
]


class ManifestField(BaseModel):
    """Поле, которое спрашивается при создании проекта."""

    model_config = _CONFIG

    key: FieldKey
    label: NonEmptyText = Field(description="Подпись в форме создания проекта")
    type: FieldType = Field(
        description="string — строка, text — несколько строк, int — число, select — из options"
    )
    required: bool = Field(default=False, description="Без значения проект не создать")
    # validate_default: select без options в YAML тоже должен дойти до проверки ниже.
    options: list[Annotated[NonEmptyText, Field(max_length=FIELD_STRING_MAX_LENGTH)]] = Field(
        default_factory=list,
        validate_default=True,
        description="Варианты для type: select; у других типов их нет",
    )
    default: DefaultText | StrictInt | None = Field(
        default=None,
        description="Значение, если поле не передано: того же типа, у select — одно из options",
    )

    @field_validator("options")
    @classmethod
    def _options_only_for_select(cls, options: list[str], info: ValidationInfo) -> list[str]:
        # Если сам type неверный, его ошибку уже покажут; здесь его нет в info.data.
        field_type = info.data.get("type")
        if field_type == "select" and not options:
            raise ValueError("у поля type: select нужен непустой список options")
        if field_type not in (None, "select") and options:
            raise ValueError("options бывают только у поля type: select")
        if len(set(options)) != len(options):
            raise ValueError("варианты в options повторяются")
        return options

    @field_validator("default")
    @classmethod
    def _default_matches_type(
        cls, default: str | int | None, info: ValidationInfo
    ) -> str | int | None:
        field_type = info.data.get("type")
        if default is None or field_type is None:
            return default
        if field_type == "int" and not isinstance(default, int):
            raise ValueError("у поля type: int default должен быть числом")
        if field_type != "int" and not isinstance(default, str):
            raise ValueError(f"у поля type: {field_type} default должен быть строкой")
        limit = MAX_VALUE_LENGTH.get(field_type)
        if isinstance(default, str) and limit is not None and len(default) > limit:
            raise ValueError(f"у поля type: {field_type} default длиннее {limit} символов")
        # options нет в info.data, если в них самих ошибка — её покажет их проверка.
        options = info.data.get("options")
        if field_type == "select" and options is not None and default not in options:
            raise ValueError("default должен быть одним из options")
        return default


class ManifestSection(BaseModel):
    """Раздел отчёта: файл и указания для ИИ, что в нём писать."""

    model_config = _CONFIG

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="Латиница, цифры и _, например goal")
    title: NonEmptyText = Field(description="Название раздела в отчёте")
    file: TexFile
    required: bool = Field(default=False, description="Раздел не может остаться пустым")
    guide: str = Field(default="", description="Что должно быть в разделе — коротко и проверяемо")


class TemplateManifest(BaseModel):
    """template.yaml — манифест шаблона (architecture.md 9.5)."""

    model_config = ConfigDict(extra="forbid", strict=True, title="template.yaml")

    slug: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        max_length=TEMPLATE_SLUG_MAX_LENGTH,
        description="Совпадает с именем папки шаблона, например mtuci-lab",
    )
    version: int = Field(ge=1, description="Растёт при каждом изменении шаблона")
    kind: ProjectKind = Field(description="Тип работы")
    title: NonEmptyText = Field(description="Название шаблона в списке")
    discipline: str | None = Field(default=None, description="Дисциплина — макрос \\bbtDiscipline")
    engine: Engine = Field(description="Движок LaTeX; шаблоны собираются через xelatex")
    # Правило компилятора для главного файла (9.7) строже 9.8: latexmk передаёт имя через shell.
    main: Annotated[
        FilePath,
        Field(
            pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.tex$",
            description="Главный файл, например main.tex",
        ),
    ]
    fields: list[ManifestField] = Field(
        default_factory=list, description="Поля, которые спрашиваются при создании проекта"
    )
    sections: list[ManifestSection] = Field(default_factory=list, description="Разделы отчёта")
    ai_rules: str = Field(default="", description="Правила для ИИ; пользователю не показываются")
    checks: list[str] = Field(
        default_factory=list, description="С этапа 3: id проверок из docs/checks.md"
    )

    @field_validator("fields")
    @classmethod
    def _unique_keys(cls, fields: list[ManifestField]) -> list[ManifestField]:
        _reject_repeats([field.key for field in fields], "ключ поля")
        return fields

    @field_validator("sections")
    @classmethod
    def _unique_sections(cls, sections: list[ManifestSection]) -> list[ManifestSection]:
        _reject_repeats([section.id for section in sections], "id раздела")
        _reject_repeats([section.file for section in sections], "файл раздела")
        return sections


def _reject_repeats(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"{what} {value} повторяется")
        seen.add(value)
