"""FakeRunEvents: события прогона по порядку и отмена после N-го события."""

import asyncio

import pytest

from app.modules.agent.contract import RunEvents
from tests.fake_run_events import FakeRunEvents, RecordedEvent


async def test_records_events_in_order() -> None:
    events = FakeRunEvents()
    run_events: RunEvents = events
    await run_events.tool_call("call-1", "edit_file", "Правка sections/goal.tex")
    await run_events.tool_result("call-1", True, "Изменён sections/goal.tex")
    await run_events.delta("Готово, ")
    await run_events.delta("цель записана.")
    assert events.types == ["run.tool_call", "run.tool_result", "run.delta", "run.delta"]
    assert events.events[1] == RecordedEvent(
        "run.tool_result", {"call_id": "call-1", "ok": True, "summary": "Изменён sections/goal.tex"}
    )
    assert events.text == "Готово, цель записана."


async def test_cancel_after_n_events() -> None:
    cancel = asyncio.Event()
    events = FakeRunEvents(cancel=cancel, cancel_after=2)
    await events.delta("а")
    assert not cancel.is_set()
    await events.delta("б")
    assert cancel.is_set()


def test_cancel_after_needs_event() -> None:
    with pytest.raises(ValueError, match="cancel"):
        FakeRunEvents(cancel_after=1)


def test_cancel_after_starts_at_one() -> None:
    with pytest.raises(ValueError, match="от 1"):
        FakeRunEvents(cancel=asyncio.Event(), cancel_after=0)
