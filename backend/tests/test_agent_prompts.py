from app.modules.agent.prompt_loader import render_instructions


def test_loads_markdown_instructions() -> None:
    instructions = render_instructions()

    assert instructions.startswith("Ты помогаешь студенту")
    assert "## Работа над отчётом" in instructions
