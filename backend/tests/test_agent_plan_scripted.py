import pytest

from app.modules.agent import planner
from app.modules.agent.scripted import scripted_model
from tests.fake_make_plan import plan_request
from tests.fake_project_tools import FakeProjectTools


async def test_scripted_model_supports_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner, "get_model", lambda role, key: scripted_model())
    request = await plan_request(FakeProjectTools())
    result = await planner.make_plan(request)
    assert result.status == "done"
    assert result.plan is not None
    assert [section.section_id for section in result.plan.sections] == [
        section.id for section in request.guide.sections
    ]
