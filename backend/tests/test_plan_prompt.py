from app.modules.agent.prompt_loader import render_plan_instructions


def test_plan_prompt_describes_evidence_and_missing_data() -> None:
    prompt = render_plan_instructions()
    assert "вывод" in prompt
    assert "Не выдумывай" in prompt
    assert "section_id" in prompt
    assert "2000" in prompt
