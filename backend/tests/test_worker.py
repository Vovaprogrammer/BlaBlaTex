"""Воркер: ресурсы задач открываются при старте и закрываются при остановке, задачи
модулей подключаются сами, пока воркер работает — идёт проверка сборок. Redis не нужен:
задачи здесь не ставятся в очередь."""

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from taskiq import TaskiqEvents, TaskiqState

from app.core import broker as broker_module
from app.core.broker import QUEUE_NAME, create_broker, get_events, get_sessionmaker, get_storage
from app.core.config import Settings
from app.core.events import EventBus
from app.core.storage import LocalStorage
from app.modules.builds.compiler import CompilerClient
from app.modules.chat.tasks import get_templates
from app.worker import (
    broker,
    close_resources,
    import_tasks,
    open_resources,
    shutdown,
    start_worker,
    startup,
    stop_worker,
)


async def test_resources_are_opened_and_closed(
    db_settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = db_settings.model_copy(
        update={
            "storage_dir": tmp_path / "storage",
            "compiler_url": "http://compiler.test:8080",
            "redis_url": "redis://redis.test:6379/0",
        }
    )
    state = TaskiqState()
    closed_events: list[EventBus] = []
    close_events = EventBus.close

    async def spy_close(self: EventBus) -> None:
        closed_events.append(self)
        await close_events(self)

    monkeypatch.setattr(EventBus, "close", spy_close)

    await open_resources(state, settings)
    try:
        async with get_sessionmaker(state)() as session:
            assert await session.scalar(text("SELECT 1")) == 1
        storage = get_storage(state)
        compiler: CompilerClient = state.compiler
        events = get_events(state)
        assert isinstance(storage, LocalStorage)
        assert storage.root == tmp_path / "storage"
        assert str(compiler.http.base_url) == "http://compiler.test:8080"
        # События сборок шлёт воркер — в тот же Redis, что читает API.
        assert events.redis.connection_pool.connection_kwargs["host"] == "redis.test"
        # Инструментам агента нужен реестр шаблонов — тот же, что у API.
        assert get_templates(state) is state.templates
        assert get_templates(state).get("test-lab") is not None
    finally:
        await close_resources(state)

    assert compiler.http.is_closed
    assert closed_events == [events]


async def test_worker_checks_builds_and_runs_while_running(
    db_settings: Settings, tmp_path: Path
) -> None:
    state = TaskiqState()

    await start_worker(state, db_settings.model_copy(update={"storage_dir": tmp_path / "s"}))
    watchers: list[asyncio.Task[None]] = [state.build_watcher, state.run_watcher]
    await asyncio.sleep(0)
    running = [not watcher.done() for watcher in watchers]
    await stop_worker(state)

    # Проверки зависших сборок и прерванных прогонов работают, пока работает воркер,
    # и останавливаются до того, как закроются их ресурсы.
    assert running == [True, True]
    assert all(watcher.cancelled() for watcher in watchers)
    assert state.compiler.http.is_closed


def test_broker_reads_queue_from_start_and_trims_it() -> None:
    queue = create_broker(Settings(_env_file=None, redis_url="redis://redis:6379/0"))

    assert queue.queue_name == QUEUE_NAME
    # Задачи, поставленные до первого запуска воркера, не пропадают.
    assert queue.consumer_id == "0"
    assert queue.maxlen is not None


def test_tasks_need_started_worker() -> None:
    # Задача, запущенная мимо воркера, падает с понятной ошибкой, а не KeyError.
    with pytest.raises(RuntimeError, match="воркер не запущен"):
        get_sessionmaker(TaskiqState())


def test_worker_entrypoint_runs_resources_on_worker_events() -> None:
    # taskiq worker app.worker:broker берёт брокер, к которому привязаны задачи модулей.
    assert broker is broker_module.broker
    assert startup in broker.event_handlers[TaskiqEvents.WORKER_STARTUP]
    assert shutdown in broker.event_handlers[TaskiqEvents.WORKER_SHUTDOWN]
    # В процессе API эти обработчики не запускаются: у него события CLIENT_*.
    assert startup not in broker.event_handlers[TaskiqEvents.CLIENT_STARTUP]
    # Задачи модулей зарегистрированы, хотя taskiq worker импортирует только этот модуль.
    assert broker.find_task("builds.run") is not None


def test_import_tasks_imports_only_existing_tasks_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "fake_task_modules"
    for module in ("with_tasks", "without_tasks"):
        (package / module).mkdir(parents=True)
        (package / module / "__init__.py").touch()
    (package / "__init__.py").touch()
    (package / "with_tasks" / "tasks.py").touch()
    monkeypatch.syspath_prepend(tmp_path)
    try:
        import_tasks("fake_task_modules")

        assert "fake_task_modules.with_tasks.tasks" in sys.modules
        assert "fake_task_modules.without_tasks.tasks" not in sys.modules
    finally:
        for name in [n for n in sys.modules if n.startswith("fake_task_modules")]:
            del sys.modules[name]
