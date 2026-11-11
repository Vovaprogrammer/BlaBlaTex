"""События проекта (architecture.md 9.3): поток SSE для вкладки браузера. Логика — в service.py."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Header, Response
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError

from app.core.errors import AppError, ErrorCode, request_error
from app.core.events import EventsDep, is_event_id
from app.core.shutdown import ShutdownDep
from app.modules.events import service
from app.modules.events.schemas import ProjectEvent
from app.modules.projects.dependencies import OwnedProject

router = APIRouter(tags=["events"])

logger = structlog.get_logger(__name__)

EVENTS_UNAVAILABLE_MESSAGE = "Обновления проекта сейчас недоступны. Попробуйте через минуту."
# Ответ — поток: каждое сообщение описывает ProjectEvent (OpenAPI 3.2, itemSchema).
_STREAM_CONTENT = {
    "text/event-stream": {
        "schema": {"type": "string"},
        "itemSchema": {"$ref": "#/components/schemas/ProjectEvent"},
    }
}


class EventStreamResponse(StreamingResponse):
    """Поток SSE. Не EventSourceResponse из FastAPI: с ним FastAPI ждёт от роута генератор
    и сам шлёт keep-alive `: ping`, а по контракту — `: keep-alive`."""

    media_type = "text/event-stream"


@router.get(
    "/projects/{pid}/events",
    # Отвечает EventStreamResponse. Здесь Response — как у скачивания файла: иначе
    # ответы с ошибками попали бы в openapi.json как text/event-stream, а они — JSON.
    response_class=Response,
    # Ответ уходит как есть; модель нужна, чтобы схемы событий попали в openapi.json.
    response_model=ProjectEvent,
    responses={
        200: {
            "description": "Поток событий: id, event и data — JSON из схемы события",
            "content": _STREAM_CONTENT,
        }
    },
)
async def project_events(
    project: OwnedProject,
    events: EventsDep,
    shutdown: ShutdownDep,
    last_event_id: Annotated[
        str | None,
        Header(description="Номер последнего полученного события: придёт всё, что после него"),
    ] = None,
) -> EventStreamResponse:
    """Поток событий проекта (SSE), пока клиент не закроет соединение.

    С Last-Event-ID сначала приходят пропущенные события — те, что ещё хранятся в журнале
    (около 1000 последних; журнал удаляется, если в проекте сутки ничего не происходило),
    без него — только новые. Пока событий нет, раз в 15 с приходит комментарий
    `: keep-alive`. Номер не в формате события — 422; Redis недоступен при подключении —
    500, во время потока — поток заканчивается, и клиент переподключается.

    Доступ проверяется при подключении; соединение с базой возвращается до начала потока.
    """
    # Пустой номер по стандарту SSE — «номера нет».
    seen = (last_event_id or "").strip()
    if seen and not is_event_id(seen):
        raise request_error(
            ["header", "last-event-id"], "Ожидается номер события, например 1730650000000-0"
        )
    # Redis спрашиваем и с Last-Event-ID: недоступен — пусть клиент получит ошибку и подождёт,
    # а не пустой поток, после которого переподключится сразу же.
    try:
        last = await events.last_id(project.id)
    except RedisError as error:
        logger.warning("events_unavailable", project_id=str(project.id), reason=repr(error))
        raise AppError(ErrorCode.INTERNAL, EVENTS_UNAVAILABLE_MESSAGE, 500) from error
    after = seen or last
    return EventStreamResponse(
        service.stream_events(events, project.id, after, shutdown),
        # Поток не кэшируется, и прокси (nginx) не копит его, а отдаёт сразу.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
