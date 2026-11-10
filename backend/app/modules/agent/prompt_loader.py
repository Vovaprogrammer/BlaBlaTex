"""Загрузка Markdown-шаблонов инструкций агента."""

from jinja2 import Environment, PackageLoader, StrictUndefined

_ENV = Environment(
    loader=PackageLoader("app.modules.agent", "prompts"),
    undefined=StrictUndefined,
    autoescape=False,
    auto_reload=False,
)


def render_instructions() -> str:
    """Системная роль и инструкции по подготовке отчёта."""
    system = _ENV.get_template("system.md").render()
    report = _ENV.get_template("report.md").render()
    return f"{system}\n\n{report}"
