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
from app.core.ratelimit import RedisRateLimiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.shutdown import Shutdown
from app.core.storage import LocalStorage
from app.modules.auth.dependencies import csrf_guard
from app.modules.auth.router import account_router, tokens_router
from app.modules.auth.router import router as auth_router
from app.modules.builds.router import router as builds_router
from app.modules.chat.router import router as chat_router
from app.modules.chat.router import runs_router
from app.modules.checks.router import router as checks_router
from app.modules.events.router import router as events_router
from app.modules.health.router import router as health_router
from app.modules.llm.router import router as llm_router
from app.modules.materials.router import router as materials_router
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
            # Сигнал остановки сначала закрывает потоки событий, иначе uvicorn ждал бы
            # их без срока и до остального не дошёл бы (core/shutdown.py).
            resources.enter_context(app.state.shutdown.on_signals())
            engine = create_engine(settings)
            resources.push_async_callback(engine.dispose)
            app.state.db_engine = engine
            app.state.db_sessionmaker = create_sessionmaker(engine)
            # К Redis клиент подключится при первом событии, как и брокер ниже.
            events = EventBus.from_settings(settings)
            resources.push_async_callback(events.close)
            app.state.events = events
            # Счётчики лимитов запросов (core/ratelimit.py) — в том же Redis, со своим клиентом.
            rate_limiter = RedisRateLimiter.from_settings(settings)
            resources.push_async_callback(rate_limiter.close)
            app.state.rate_limiter = rate_limiter
            # broker.startup() здесь не нужен: он создаёт в Redis группу воркеров — это делает
            # воркер, а без вызова API запускается и без Redis. К Redis брокер подключится
            # при первой задаче. Адрес он берёт из окружения (core/broker.py), а не из
            # settings: к нему привязаны задачи при импорте. shutdown закрывает его соединения.
            resources.push_async_callback(broker.shutdown)
            yield

    # В проде документации нет (architecture.md 13): студентам она не нужна, а описание
    # API лежит в backend/openapi.json.
    prod = settings.app_env == "prod"
    app = FastAPI(
        title="BlaBlaTex API",
        docs_url=None if prod else "/api/docs",
        redoc_url=None,
        openapi_url=None if prod else "/api/openapi.json",
        lifespan=lifespan,
        # Защита от CSRF — на каждом маршруте, ещё до его собственных зависимостей.
        dependencies=[Depends(csrf_guard)],
    )
    # Роуты читают настройки отсюда, а не из get_settings(): так видят и настройки тестов.
    app.state.settings = settings
    app.state.storage = LocalStorage(settings.storage_dir)
    # Отметку остановки ставят сигналы, пока работает lifespan; без него (тесты) — никто.
    app.state.shutdown = Shutdown()
    # Читается здесь, а не в lifespan: чтение файлов не блокирует цикл событий,
    # и реестр есть и в тестах, где lifespan не запускается.
    app.state.templates = load_templates(settings.templates_dir)
    register_error_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_router, prefix=API_PREFIX)
    routers = (
        auth_router,
        account_router,
        tokens_router,
        profiles_router,
        templates_router,
        projects_router,
        changesets_router,
        materials_router,
        chat_router,
        runs_router,
        builds_router,
        checks_router,
        events_router,
        llm_router,
    )
    for router in routers:
        app.include_router(router, prefix=API_PREFIX, responses=ERROR_RESPONSES)
    return app


# Объект для `fastapi dev app/main.py` и uvicorn.
app = create_app()
