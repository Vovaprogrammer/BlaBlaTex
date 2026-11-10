from app.modules.agent.prompt_loader import render_instructions
from tests.fake_project_tools import DEFAULT_GUIDE


def test_loads_markdown_instructions() -> None:
    instructions = render_instructions()

    assert instructions.startswith("Ты помогаешь студенту")
    assert "## Работа над отчётом" in instructions
    assert "### Шаблон проекта" not in instructions


def test_renders_sections_rules_and_macros_from_guide() -> None:
    instructions = render_instructions(DEFAULT_GUIDE)

    assert DEFAULT_GUIDE.discipline in instructions
    assert "`sections/goal.tex` (обязательный раздел)" in instructions
    assert DEFAULT_GUIDE.sections[0].guide in instructions
    assert DEFAULT_GUIDE.ai_rules in instructions
    assert DEFAULT_GUIDE.macros[0].usage in instructions
    assert r"Номер работы — `\bbtLabNumber`" in instructions
    assert r"Группа — `\bbtGroup`" in instructions
