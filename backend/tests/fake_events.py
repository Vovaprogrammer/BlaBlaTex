"""Журнал событий для тестов (architecture.md 9.3): события складываются в список, Redis
не нужен. Проверяет data так же, как настоящий EventBus."""

from dataclasses import dataclass
from uuid import UUID

from app.core.events import EventData, EventType, check_data


@dataclass(frozen=True)
class PublishedEvent:
    project_id: UUID
    type: EventType
    data: EventData


class FakeEvents:
    """EventPublisher, который запоминает события по порядку."""

    def __init__(self) -> None:
        self.published: list[PublishedEvent] = []

    @property
    def types(self) -> list[EventType]:
        return [event.type for event in self.published]

    async def publish(self, project_id: UUID, type_: EventType, data: EventData) -> str | None:
        check_data(type_, data)
        self.published.append(PublishedEvent(project_id, type_, data))
        return f"{len(self.published)}-0"
