"""Фейки для make_plan (architecture.md 9.4).

- plan_request — вход make_plan над FakeProjectTools: так A3.1 тестирует make_plan без базы,
  воркера и Redis, с тем же списком материалов и справкой шаблона, что даёт воркер.
- FakeMakePlan — make_plan для тестов воркера: возвращает заданный итог, бросает
  исключение или ждёт отмены и запоминает, с чем его вызвали.
"""

import asyncio
import uuid
from collections.abc import Sequence
from decimal import Decimal

from app.modules.agent.contract import (
    HistoryMessage,
    ModelUsage,
    PlanRequest,
    PlanResult,
)
from app.modules.plans.schemas import PlanSection, ReportPlan
from app.modules.projects.tools import ToolContext
from tests.fake_project_tools import FakeProjectTools

PLAN_USAGE = ModelUsage(model="test-model", tokens_in=300, tokens_out=80, cost=Decimal("0.0030"))
PLAN_REQUEST = "Составь план отчёта"


async def plan_request(
    tools: FakeProjectTools,
    history: Sequence[HistoryMessage] = (HistoryMessage(role="user", text=PLAN_REQUEST),),
    *,
    max_tokens: int = 100_000,
) -> PlanRequest:
    """PlanRequest, как его собирает воркер: справка шаблона и материалы — из tools."""
    context = ToolContext(
        project_id=uuid.uuid4(), user_id=uuid.uuid4(), actor="ai", changeset_id=uuid.uuid4()
    )
    guide = await tools.get_template_guide()
    materials = await tools.list_materials()
    tools.calls.clear()
    return PlanRequest(
        run_id=uuid.uuid4(),
        history=list(history),
        guide=guide,
        materials=materials,
        context=context,
        tools=tools,
        cancel=asyncio.Event(),
        max_tokens=max_tokens,
    )


def plan_of(*sections: tuple[str, list[str], str], unassigned: Sequence[str] = ()) -> ReportPlan:
    """План из (section_id, материалы, заметка); title модель может не знать — пусто."""
    return ReportPlan(
        sections=[
            PlanSection(section_id=section_id, title="", materials=materials, note=note)
            for section_id, materials, note in sections
        ],
        unassigned=list(unassigned),
    )


class FakeMakePlan:
    """make_plan с заданным поведением. requests — с чем его вызвали."""

    def __init__(
        self,
        result: PlanResult | None = None,
        *,
        error: Exception | None = None,
        wait_cancel: bool = False,
    ) -> None:
        self.result = result or PlanResult(status="done", plan=plan_of(), usage=PLAN_USAGE)
        self.error = error
        self.wait_cancel = wait_cancel
        self.requests: list[PlanRequest] = []

    async def __call__(self, request: PlanRequest) -> PlanResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.wait_cancel:
            await request.cancel.wait()
            return PlanResult(status="cancelled", usage=PLAN_USAGE)
        return self.result
