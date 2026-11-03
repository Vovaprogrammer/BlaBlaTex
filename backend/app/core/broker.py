"""Очередь фоновых задач: Taskiq поверх Redis (architecture.md 2, 4).

API ставит задачу в очередь (`await task.kiq(...)`) и сразу отвечает, а выполняет её
воркер — отдельный процесс, точка входа app/worker.py. Задачи лежат в
modules/<name>/tasks.py и регистрируются у этого брокера.

Ресурсы воркера (база, хранилище файлов, клиент компилятора, события) открывает app/worker.py
при старте и кладёт в broker.state; задачи получают их через зависимости ниже, как
роуты FastAPI получают свои через Depends.
"""

from typing import Annotated, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import TaskiqDepends, TaskiqState
from taskiq_redis import RedisStreamBroker

from app.core.config import Settings, get_settings
from app.core.events import EventBus
from app.core.storage import Storage

# Ключ потока в Redis и группа воркеров. Свои имена, а не taskiq: Redis может быть общим.
QUEUE_NAME = "blablatex:tasks"
CONSUMER_GROUP = "blablatex-workers"
# Сколько сообщений хранит поток: выполненные из него не удаляются, Redis обрезает старые.
QUEUE_MAXLEN = 10_000


def create_broker(settings: Settings) -> RedisStreamBroker:
    """Брокер на потоке Redis. Подключение открывается при первой задаче, а не здесь.

    Почему поток, а не список (ListQueueBroker): список ждёт задачу без срока, а redis 8
    по умолчанию обрывает чтение через 5 с — простаивающий воркер падал бы каждые 5 с.
    Поток спрашивает новые задачи каждые 2 с.

    Сообщение подтверждается, когда задача закончилась. Если воркер упал посреди задачи
    или она идёт дольше 10 минут, сообщение получит другой воркер. Поэтому задача должна
    выдерживать повтор: итог пишется в базу, и задача сначала проверяет его там.
    """
    return RedisStreamBroker(
        settings.redis_base_url,
        queue_name=QUEUE_NAME,
        consumer_group_name=CONSUMER_GROUP,
        # Группа, созданная впервые, читает поток с начала: задачи, которые API поставил
        # до первого запуска воркера, не пропадут.
        consumer_id="0",
        maxlen=QUEUE_MAXLEN,
    )


# Один брокер на процесс: к нему привязываются задачи при импорте modules/*/tasks.py.
broker = create_broker(get_settings())


def get_sessionmaker(
    state: Annotated[TaskiqState, TaskiqDepends()],
) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий БД воркера. Задача открывает сессию сама и держит её недолго."""
    sessionmaker: async_sessionmaker[AsyncSession] = get_resource(state, "sessionmaker")
    return sessionmaker


def get_storage(state: Annotated[TaskiqState, TaskiqDepends()]) -> Storage:
    """Хранилище файлов воркера — та же папка, что у API."""
    storage: Storage = get_resource(state, "storage")
    return storage


def get_events(state: Annotated[TaskiqState, TaskiqDepends()]) -> EventBus:
    """Журнал событий проектов (9.3): задачи шлют в него события сборок и других задач."""
    events: EventBus = get_resource(state, "events")
    return events


# Any: TaskiqState хранит значения без типов; зависимости приводят их к своему типу.
def get_resource(state: TaskiqState, name: str) -> Any:
    """Ресурс воркера из state по имени — для зависимостей задач в модулях."""
    if name not in state:
        raise RuntimeError(
            f"Нет ресурса воркера {name}: воркер не запущен (app/worker.py). "
            "В тестах — передайте зависимость задаче явно."
        )
    return state[name]


WorkerSessions = Annotated[async_sessionmaker[AsyncSession], TaskiqDepends(get_sessionmaker)]
WorkerStorage = Annotated[Storage, TaskiqDepends(get_storage)]
WorkerEvents = Annotated[EventBus, TaskiqDepends(get_events)]
