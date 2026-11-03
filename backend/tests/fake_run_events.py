"""RunEvents для тестов агента (architecture.md 9.4): события прогона складываются в список.

Типы событий — как в 9.3, но без run_id и message_id: их добавляет бэкенд.
"""

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class RecordedEvent:
    type: str
    data: dict[str, str | bool]


class FakeRunEvents:
    """Складывает события в events. cancel_after=N — взвести cancel после N-го события:
    так тест проверяет отмену посреди стрима."""

    def __init__(
        self, cancel: asyncio.Event | None = None, cancel_after: int | None = None
    ) -> None:
        if cancel_after is not None and cancel is None:
            raise ValueError("Для cancel_after нужен cancel")
        self.events: list[RecordedEvent] = []
        self._cancel = cancel
        self._cancel_after = cancel_after

    @property
    def types(self) -> list[str]:
        return [event.type for event in self.events]

    @property
    def text(self) -> str:
        """Весь текст ответа из run.delta."""
        return "".join(
            str(event.data["text"]) for event in self.events if event.type == "run.delta"
        )

    async def delta(self, text: str) -> None:
        self._record("run.delta", {"text": text})

    async def tool_call(self, call_id: str, tool: str, summary: str) -> None:
        self._record("run.tool_call", {"call_id": call_id, "tool": tool, "summary": summary})

    async def tool_result(self, call_id: str, ok: bool, summary: str) -> None:
        self._record("run.tool_result", {"call_id": call_id, "ok": ok, "summary": summary})

    def _record(self, type_: str, data: dict[str, str | bool]) -> None:
        self.events.append(RecordedEvent(type_, data))
        if self._cancel is not None and len(self.events) == self._cancel_after:
            self._cancel.set()
