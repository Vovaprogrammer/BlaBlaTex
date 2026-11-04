"""Общие фикстуры тестов."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import BACKEND_DIR, Settings
from app.core.db import create_engine, create_sessionmaker, get_session
from app.core.events import EventBus
from app.core.storage import LocalStorage
from app.main import create_app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.builds.dependencies import get_enqueue
from app.modules.projects.dependencies import get_extract_materials
from tests.build_worker import BuildWorker
from tests.fake_events import FakeEvents
from tests.helpers import (
    CSRF,
    PASSWORD,
    STUDENT_EMAIL,
    TEMPLATE_FIXTURES,
    TEST_TEMPLATES,
    CreateProject,
    SignIn,
    SignUp,
    drop_database,
)
from tests.live_builds import Live

# Общие контрактные тесты ProjectTools лежат не в test_*.py: без этого pytest
# не показал бы значения в упавших assert.
pytest.register_assert_rewrite("tests.project_tools_contract")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Настройки тестов: без личного .env разработчика, хранилище — во временной папке,
    шаблоны — фикстуры."""
    return Settings(
        _env_file=None,
        app_env="test",
        storage_dir=tmp_path / "storage",
        templates_dir=TEMPLATE_FIXTURES,
    )


@pytest.fixture
def events() -> FakeEvents:
    """События, которые отправил код под тестом, — вместо журнала в Redis."""
    return FakeEvents()


@pytest.fixture
def extractions() -> list[uuid.UUID]:
    """Материалы, для которых код под тестом разбудил извлечение текста, — вместо очереди."""
    return []


@pytest.fixture
def app(settings: Settings, events: FakeEvents, extractions: list[uuid.UUID]) -> FastAPI:
    """Свежий экземпляр приложения на каждый тест. События складываются в events;
    lifespan, если тест его запустит, заменит их настоящим журналом. Задания на извлечение
    текста не уходят в Redis, а складываются в extractions."""
    app = create_app(settings)
    app.state.events = events

    async def extract(file_ids: Sequence[uuid.UUID]) -> None:
        extractions.extend(file_ids)

    app.dependency_overrides[get_extract_materials] = lambda: extract
    return app


@pytest.fixture
async def event_bus() -> AsyncIterator[EventBus]:
    """Журнал событий на настоящем Redis — адрес из окружения и .env, как у приложения.

    Ключи — со своим префиксом прогона и теста: одновременные прогоны и данные dev-воркера
    в том же Redis не мешают. После теста ключи удаляются.
    """
    prefix = f"blablatex-test-{os.getpid()}-{uuid.uuid4().hex[:8]}:events"
    bus = EventBus.from_settings(Settings(app_env="test"), prefix=prefix)
    try:
        await bus.redis.ping()
    except RedisError as error:
        await bus.close()
        pytest.fail(
            f"Нет подключения к Redis ({error}). "
            "Запустите docker compose up -d и проверьте REDIS_* в .env.",
            pytrace=False,
        )
    try:
        yield bus
        keys = [key async for key in bus.redis.scan_iter(match=f"{bus.prefix}:*")]
        if keys:
            await bus.redis.delete(*keys)
    finally:
        await bus.close()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент к приложению, без сети."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="session")
def db_settings() -> Iterator[Settings]:
    """Настройки своей базы прогона <POSTGRES_DB>_test_<номер процесса>.

    Подключение — из окружения и .env, как у приложения: локально там свои порт и пароль.
    Рабочая база не трогается: имя тестовой всегда с суффиксом. Номер процесса в имени —
    чтобы одновременные прогоны (два терминала, несколько агентов) не удаляли базу друг
    у друга. В начале прогона база создаётся заново, в конце удаляется.
    Миграции применяются один раз за прогон. Фикстура синхронная: env.py Alembic
    сам запускает asyncio.run, а внутри работающего цикла событий это невозможно.
    """
    base = Settings(app_env="test")
    name = f"{base.postgres_db}_test_{os.getpid()}"
    db_settings = base.model_copy(update={"postgres_db": name, "templates_dir": TEMPLATE_FIXTURES})
    try:
        asyncio.run(drop_database(base.database_url, name, create_again=True))
    except OSError as error:
        pytest.fail(
            f"Нет подключения к Postgres на {base.postgres_host}:{base.postgres_port} ({error}). "
            "Запустите docker compose up -d и проверьте POSTGRES_* в .env.",
            pytrace=False,
        )

    config = Config(toml_file=BACKEND_DIR / "pyproject.toml")
    config.attributes["database_url"] = db_settings.database_url
    command.upgrade(config, "head")
    yield db_settings
    asyncio.run(drop_database(base.database_url, name, create_again=False))


@pytest.fixture
async def db_engine(db_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Движок к тестовой базе. Без пула: соединение не переживает цикл событий теста."""
    engine = create_async_engine(db_settings.database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия внутри внешней транзакции, которая откатывается после теста.

    commit() в коде под тестом фиксирует только SAVEPOINT, поэтому данные одного теста
    не видны другим. Остальные настройки сессии — как у приложения.
    """
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = create_sessionmaker(connection)(join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def db_client(app: FastAPI, client: AsyncClient, db_session: AsyncSession) -> AsyncClient:
    """HTTP-клиент, в котором роуты получают db_session вместо своей сессии."""

    async def test_session() -> AsyncSession:
        return db_session

    app.dependency_overrides[get_session] = test_session
    return client


@pytest.fixture
def build_worker(app: FastAPI, db_session: AsyncSession, events: FakeEvents) -> BuildWorker:
    """Воркер сборок в сессии теста: POST /builds ставит сборки ему, run() их собирает.
    События сборок складываются в events — туда же, куда события API."""
    worker = BuildWorker(db_session, app.state.storage, events=events)
    app.dependency_overrides[get_enqueue] = lambda: worker.enqueue
    return worker


@pytest.fixture
def sign_up(db_client: AsyncClient) -> SignUp:
    """Регистрирует пользователя через API; дальше db_client ходит от его имени."""

    async def sign_up(email: str) -> None:
        # Cookie прошлого пользователя убираем, иначе регистрация пошла бы с ней.
        db_client.cookies.clear()
        response = await db_client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD, "consent": True}
        )
        assert response.status_code == 201, response.text

    return sign_up


@pytest.fixture
def sign_in(db_client: AsyncClient) -> SignIn:
    """Входит под уже зарегистрированным пользователем; дальше db_client ходит от его имени."""

    async def sign_in(email: str) -> None:
        db_client.cookies.clear()
        response = await db_client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text

    return sign_in


@pytest.fixture
async def user_client(db_client: AsyncClient, sign_up: SignUp) -> AsyncClient:
    """Клиент, вошедший как студент; заголовок защиты от CSRF — во всех запросах."""
    await sign_up(STUDENT_EMAIL)
    db_client.headers.update(CSRF)
    return db_client


@pytest.fixture
def create_project(db_client: AsyncClient) -> CreateProject:
    """Создаёт проект текущего пользователя из тестового шаблона через POST /projects."""

    async def create_project(
        template_slug: str = "test-lab", title: str = "ЛР 1"
    ) -> dict[str, Any]:
        body = {
            "title": title,
            "template_slug": template_slug,
            "fields": TEST_TEMPLATES[template_slug],
        }
        response = await db_client.post("/api/v1/projects", json=body, headers=CSRF)
        assert response.status_code == 201, response.text
        return response.json()

    return create_project


@pytest.fixture
async def project(user_client: AsyncClient, create_project: CreateProject) -> dict[str, Any]:
    """Проект студента из шаблона test-lab, как его вернул POST /projects."""
    return await create_project()


@pytest.fixture
async def live(db_settings: Settings, tmp_path: Path) -> AsyncIterator[Live]:
    """Пул соединений к тестовой базе и новый пользователь; после теста он удаляется.

    Для воркеров и гонок: обычные тесты идут в одной транзакции, а в ней гонку не увидеть.
    """
    engine = create_engine(db_settings)
    sessionmaker = create_sessionmaker(engine)
    email = f"live-{uuid.uuid4().hex[:8]}@example.com"
    async with sessionmaker() as session:
        user, _ = await auth_service.register(session, email, PASSWORD)
    try:
        yield Live(sessionmaker, LocalStorage(tmp_path / "storage"), user.id)
    finally:
        async with sessionmaker() as session:
            await session.execute(delete(User).where(User.email == email))
            await session.commit()
        await engine.dispose()


@pytest.fixture
async def live_app(db_settings: Settings, tmp_path: Path) -> AsyncIterator[FastAPI]:
    """Приложение с настоящим пулом соединений к тестовой базе. События — в FakeEvents,
    а не в Redis разработчика: lifespan открыл бы настоящий журнал."""
    app = create_app(db_settings.model_copy(update={"storage_dir": tmp_path / "storage"}))
    async with app.router.lifespan_context(app):
        app.state.events = FakeEvents()
        yield app


@pytest.fixture
async def live_client(live_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Клиент, вошедший как новый пользователь; после теста пользователь удаляется."""
    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    transport = ASGITransport(app=live_app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=CSRF) as client:
        response = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD, "consent": True}
        )
        assert response.status_code == 201, response.text
        try:
            yield client
        finally:
            async with live_app.state.db_sessionmaker() as session:
                await session.execute(delete(User).where(User.email == email))
                await session.commit()
