"""События потока GET /projects/{pid}/events для openapi.json (architecture.md 9.3).

По этим схемам фронт получает типы событий (pnpm gen:api) и не пишет их руками.
Сообщение потока — id, event и data. На проводе data — строка JSON, здесь она описана
уже разобранной: объектом своего типа события.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel

from app.core.events import (
    BuildFinishedData,
    BuildStartedData,
    FileChangedData,
    FileDeletedData,
    FileMovedData,
    MaterialReadyData,
    ProjectLockedData,
    ProjectUnlockedData,
    RunDeltaData,
    RunFinishedData,
    RunStartedData,
    RunToolCallData,
    RunToolResultData,
)


class _Event(BaseModel):
    id: str = Field(description="Номер события; с ним клиент переподключается в Last-Event-ID")


class FileChangedEvent(_Event):
    event: Literal["file.changed"]
    data: FileChangedData


class FileDeletedEvent(_Event):
    event: Literal["file.deleted"]
    data: FileDeletedData


class FileMovedEvent(_Event):
    event: Literal["file.moved"]
    data: FileMovedData


class MaterialReadyEvent(_Event):
    event: Literal["material.ready"]
    data: MaterialReadyData


class BuildStartedEvent(_Event):
    event: Literal["build.started"]
    data: BuildStartedData


class BuildFinishedEvent(_Event):
    event: Literal["build.finished"]
    data: BuildFinishedData


class RunStartedEvent(_Event):
    event: Literal["run.started"]
    data: RunStartedData


class RunDeltaEvent(_Event):
    event: Literal["run.delta"]
    data: RunDeltaData


class RunToolCallEvent(_Event):
    event: Literal["run.tool_call"]
    data: RunToolCallData


class RunToolResultEvent(_Event):
    event: Literal["run.tool_result"]
    data: RunToolResultData


class RunFinishedEvent(_Event):
    event: Literal["run.finished"]
    data: RunFinishedData


class ProjectLockedEvent(_Event):
    event: Literal["project.locked"]
    data: ProjectLockedData


class ProjectUnlockedEvent(_Event):
    event: Literal["project.unlocked"]
    data: ProjectUnlockedData


class ProjectEvent(
    RootModel[
        Annotated[
            FileChangedEvent
            | FileDeletedEvent
            | FileMovedEvent
            | MaterialReadyEvent
            | BuildStartedEvent
            | BuildFinishedEvent
            | RunStartedEvent
            | RunDeltaEvent
            | RunToolCallEvent
            | RunToolResultEvent
            | RunFinishedEvent
            | ProjectLockedEvent
            | ProjectUnlockedEvent,
            Field(discriminator="event"),
        ]
    ]
):
    """Одно событие потока; его тип — в поле event."""
