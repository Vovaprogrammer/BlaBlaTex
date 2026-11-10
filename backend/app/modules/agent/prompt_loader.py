"""Загрузка Markdown-шаблонов инструкций агента."""

from jinja2 import Environment, PackageLoader, StrictUndefined

from app.modules.projects.tools import TemplateGuide

_ENV = Environment(
    loader=PackageLoader("app.modules.agent", "prompts"),
    undefined=StrictUndefined,
    autoescape=False,
    auto_reload=False,
    trim_blocks=True,
)


def render_instructions(guide: TemplateGuide | None = None) -> str:
    """Системная роль и инструкции по подготовке отчёта."""
    system = _ENV.get_template("system.md").render()
    report = _ENV.get_template("report.md").render(guide=guide)
    return f"{system}\n\n{report}"
