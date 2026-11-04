"""Точка входа API: фабрика приложения FastAPI."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI

from app.core.broker import broker
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.errors import ERROR_RESPONSES, register_error_handlers
from app.core.events import EventBus
from app.core.logging import configure_logging
from app.core.storage import LocalStorage
from app.modules.auth.dependencies import csrf_guard
from app.modules.auth.router import router as auth_router
from app.modules.builds.router import router as builds_router
from app.modules.events.router import router as events_router
from app.modules.health.router import router as health_router
from app.modules.profiles.router import router as profiles_router
from app.modules.projects.router import changesets_router
from app.modules.projects.router import router as projects_router
from app.modules.templates.registry import load_templates
from app.modules.templates.router import router as templates_router

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение: логи, БД, хранилище файлов, реестр шаблонов, ошибки по 9.2,
    документация под /api, роутеры под /api/v1.

    Без аргумента настройки берутся из окружения и .env; тесты передают свои.
    Шаблон с ошибкой — TemplateError: приложение не запускается, пока шаблон не исправят.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Пул соединений с базой, клиент событий проектов и подключение к очереди задач
        # живут, пока работает сервер, и закрываются при остановке — в обратном порядке,
        # даже если закрыть одно не удалось. К компилятору API не ходит: собирает воркер.
        async with AsyncExitStack() as resources:
            engine = create_engine(settings)
            resources.push_async_callback(engine.dispose)
            app.state.db_engine = engine
            app.state.db_sessionmaker = create_sessionmaker(engine)
            # К Redis клиент подключится при первом событии, как и брокер ниже.
            events = EventBus.from_settings(settings)
            resources.push_async_callback(events.close)
            app.state.events = events
            # broker.startup() здесь не нужен: он создаёт в Redis группу воркеров — это делает
            # воркер, а без вызова API запускается и без Redis. К Redis брокер подключится
            # при первой задаче. Адрес он берёт из окружения (core/broker.py), а не из
            # settings: к нему привязаны задачи при импорте. shutdown закрывает его соединения.
            resources.push_async_callback(broker.shutdown)
            yield

    app = FastAPI(
        title="BlaBlaTex API",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        # Защита от CSRF — на каждом маршруте, ещё до его собственных зависимостей.
        dependencies=[Depends(csrf_guard)],
    )
    # Роуты читают настройки отсюда, а не из get_settings(): так видят и настройки тестов.
    app.state.settings = settings
    app.state.storage = LocalStorage(settings.storage_dir)
    # Читается здесь, а не в lifespan: чтение файлов не блокирует цикл событий,
    # и реестр есть и в тестах, где lifespan не запускается.
    app.state.templates = load_templates(settings.templates_dir)
    register_error_handlers(app)
    app.include_router(health_router, prefix=API_PREFIX)
    routers = (
        auth_router,
        profiles_router,
        templates_router,
        projects_router,
        changesets_router,
        builds_router,
        events_router,
    )
    for router in routers:
        app.include_router(router, prefix=API_PREFIX, responses=ERROR_RESPONSES)
    return app


# Объект для `fastapi dev app/main.py` и uvicorn.
app = create_app()
