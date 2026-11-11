"""Точка входа воркера: `uv run taskiq worker app.worker:broker` (architecture.md 2, 4).

Воркер — отдельный процесс, который выполняет задачи из очереди: сборки, позже прогоны
агента и извлечение текста. Базу, хранилище файлов, клиент компилятора и клиент событий
проектов он открывает сам при старте и закрывает при остановке; пока он работает, фоновая
проверка находит зависшие и потерянные сборки. Задачи из modules/*/tasks.py подключаются
здесь же: новому модулю с задачами этот файл менять не нужно.
"""

import asyncio
import importlib
import importlib.util
import pkgutil
from contextlib import AsyncExitStack, suppress

import structlog
from taskiq import TaskiqEvents, TaskiqState

from app.core.broker import broker
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker, import_models
from app.core.events import EventBus
from app.core.logging import configure_logging
from app.core.storage import LocalStorage
from app.modules.builds.compiler import CompilerClient, create_http_client
from app.modules.templates.registry import load_templates

# Taskiq ищет брокер по пути app.worker:broker.
__all__ = ["broker"]

logger = structlog.get_logger(__name__)


async def open_resources(state: TaskiqState, settings: Settings) -> None:
    """Открывает ресурсы задач и кладёт их в state (их берут зависимости core/broker.py
    и задач модулей).

    Пул соединений с базой, HTTP-соединения с компилятором и клиент событий проектов
    живут, пока работает воркер. Реестр шаблонов нужен инструментам агента.
    """
    engine = create_engine(settings)
    state.db_engine = engine
    state.sessionmaker = create_sessionmaker(engine)
    state.storage = LocalStorage(settings.storage_dir)
    state.compiler = CompilerClient(create_http_client(settings.compiler_base_url))
    state.events = EventBus.from_settings(settings)
    state.templates = load_templates(settings.templates_dir)


async def close_resources(state: TaskiqState) -> None:
    """Закрывает ресурсы в обратном порядке, даже если закрыть одно не удалось."""
    compiler: CompilerClient = state.compiler
    events: EventBus = state.events
    async with AsyncExitStack() as resources:
        resources.push_async_callback(state.db_engine.dispose)
        resources.push_async_callback(events.close)
        resources.push_async_callback(compiler.http.aclose)


async def start_worker(state: TaskiqState, settings: Settings) -> None:
    """Открывает ресурсы и запускает фоновые проверки: зависших и потерянных сборок,
    прерванных и потерянных прогонов агента, материалов без извлечённого текста."""
    # Не в начале файла: модули задач импортируются только после всех моделей (ниже).
    from app.modules.builds.tasks import watch_builds
    from app.modules.chat.tasks import watch_runs
    from app.modules.materials.tasks import watch_materials

    await open_resources(state, settings)
    state.build_watcher = asyncio.create_task(watch_builds(state.sessionmaker, state.events))
    state.run_watcher = asyncio.create_task(watch_runs(state.sessionmaker, state.events))
    state.material_watcher = asyncio.create_task(watch_materials(state.sessionmaker))


async def stop_worker(state: TaskiqState) -> None:
    """Останавливает фоновые проверки, потом закрывает ресурсы: они ими пользуются."""
    watchers: list[asyncio.Task[None]] = [
        state.build_watcher,
        state.run_watcher,
        state.material_watcher,
    ]
    for watcher in watchers:
        watcher.cancel()
    for watcher in watchers:
        with suppress(asyncio.CancelledError):
            await watcher
    await close_resources(state)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    settings = get_settings()
    configure_logging(settings)
    await start_worker(state, settings)
    logger.info("worker_started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    await stop_worker(state)
    logger.info("worker_stopped")


def import_tasks(package: str = "app.modules") -> None:
    """Импортирует <package>/*/tasks.py: задачи регистрируются у брокера при импорте.

    Сам `taskiq worker` импортирует только модуль с брокером.
    """
    root = importlib.import_module(package)
    for module in pkgutil.iter_modules(root.__path__):
        name = f"{package}.{module.name}.tasks"
        if module.ispkg and importlib.util.find_spec(name) is not None:
            importlib.import_module(name)


# Сначала все модели, потом задачи. Задачи импортируют не все модели: users, например, —
# только API. Без них SQLAlchemy не находит таблицу по внешнему ключу, и первая запись
# агента (changeset → users) падает. Так и задача, которая строит запрос при импорте,
# видит все таблицы.
import_models()
import_tasks()
