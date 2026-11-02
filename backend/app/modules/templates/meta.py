"""meta.tex проекта (architecture.md 9.6): макросы \\bbt... из профиля и полей проекта.

Файлы шаблона — чистый LaTeX: данные студента и проекта попадают в отчёт только через
эти макросы. Макросы задаются через \\def: так meta.tex работает и когда класс уже объявил
их значения по умолчанию через \\providecommand, и когда не объявлял.
"""

import unicodedata

from app.modules.profiles.models import Profile
from app.modules.templates.manifest import TemplateManifest, macro_suffix

# Город на титульном листе (9.6); в профиле его нет.
DEFAULT_CITY = "Москва"
# Год сборки, а не создания проекта: ВКР, начатая осенью, защищается уже в следующем году.
YEAR = "\\the\\year"
HEADER = (
    "% Создаётся автоматически из профиля и полей проекта. Не редактируйте: изменения пропадут."
)

# Спецсимволы TeX из 9.6 и их запись текстом. Один проход translate: замены не задевают
# друг друга (обратная косая из \& не экранируется повторно).
_ESCAPES = str.maketrans(
    {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
)


def escape_latex(text: str) -> str:
    """Текст для подстановки в TeX: спецсимволы экранированы.

    Переводы строк приводятся к \\n (пустая строка в тексте — новый абзац), прочие
    управляющие символы, кроме табуляции, убираются: TeX на них ругается.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char for char in text if char in "\n\t" or unicodedata.category(char) != "Cc")
    return text.translate(_ESCAPES)


def _short_name(profile: Profile) -> str:
    """«Фамилия И. О.»; между частями неразрывный пробел ~, чтобы инициалы не отрывались."""
    initials = [
        escape_latex(name.strip()[0]) + "."
        for name in (profile.first_name, profile.middle_name)
        if name.strip()
    ]
    parts = [escape_latex(profile.last_name.strip())] if profile.last_name.strip() else []
    return "~".join(parts + initials)


def render_meta(profile: Profile, manifest: TemplateManifest, fields: dict[str, str | int]) -> str:
    """Текст meta.tex: макросы профиля, шаблона и каждого поля шаблона.

    Поле без значения даёт пустой макрос: \\input{meta} не падает на неопределённом.
    """
    full_name = " ".join(
        name.strip()
        for name in (profile.last_name, profile.first_name, profile.middle_name)
        if name.strip()
    )
    macros = {
        "LastName": escape_latex(profile.last_name.strip()),
        "FirstName": escape_latex(profile.first_name.strip()),
        "MiddleName": escape_latex(profile.middle_name.strip()),
        "ShortName": _short_name(profile),
        "FullName": escape_latex(full_name),
        "Group": escape_latex(profile.group_name.strip()),
        "Faculty": escape_latex(profile.faculty.strip()),
        "Department": escape_latex(profile.department.strip()),
        "Discipline": escape_latex(manifest.discipline or ""),
        "Year": YEAR,
        "City": DEFAULT_CITY,
    }
    for field in manifest.fields:
        value = fields.get(field.key)
        macros[macro_suffix(field.key)] = "" if value is None else escape_latex(str(value))
    lines = [HEADER, *(f"\\def\\bbt{name}{{{value}}}" for name, value in macros.items())]
    return "\n".join(lines) + "\n"
