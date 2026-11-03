"""Точка входа воркера: `uv run taskiq worker app.worker:broker` (architecture.md 2, 4).

Воркер — отдельный процесс, который выполняет задачи из очереди: сборки, позже прогоны
агента и извлечение текста. Базу, хранилище файлов и клиент компилятора он открывает
сам при старте и закрывает при остановке. Задачи из modules/*/tasks.py подключаются
здесь же: новому модулю с задачами этот файл менять не нужно.
"""

import importlib
import importlib.util
import pkgutil

import structlog
from taskiq import TaskiqEvents, TaskiqState

from app.core.broker import broker
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging
from app.core.storage import LocalStorage
from app.modules.builds.compiler import CompilerClient, create_http_client

# Taskiq ищет брокер по пути app.worker:broker.
__all__ = ["broker"]

logger = structlog.get_logger(__name__)


async def open_resources(state: TaskiqState, settings: Settings) -> None:
    """Открывает ресурсы задач и кладёт их в state (их берут зависимости core/broker.py).

    Пул соединений с базой и HTTP-соединения с компилятором живут, пока работает воркер.
    """
    engine = create_engine(settings)
    state.db_engine = engine
    state.sessionmaker = create_sessionmaker(engine)
    state.storage = LocalStorage(settings.storage_dir)
    state.compiler = CompilerClient(create_http_client(settings.compiler_base_url))


async def close_resources(state: TaskiqState) -> None:
    compiler: CompilerClient = state.compiler
    try:
        await compiler.http.aclose()
    finally:
        await state.db_engine.dispose()


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    settings = get_settings()
    configure_logging(settings)
    await open_resources(state, settings)
    logger.info("worker_started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    await close_resources(state)
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


import_tasks()
