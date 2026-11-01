"""Общие фикстуры тестов."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import BACKEND_DIR, Settings
from app.core.db import create_sessionmaker, get_session
from app.main import create_app
from tests.helpers import (
    CSRF,
    PASSWORD,
    STUDENT_EMAIL,
    TEST_TEMPLATES,
    CreateProject,
    SignIn,
    SignUp,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Настройки тестов: без личного .env разработчика, хранилище — во временной папке."""
    return Settings(_env_file=None, app_env="test", storage_dir=tmp_path / "storage")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Свежий экземпляр приложения на каждый тест."""
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент к приложению, без сети."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _drop_database(url: URL, name: str, *, create_again: bool) -> None:
    """Удаляет базу name, если она есть; при create_again создаёт её снова пустой."""
    # CREATE и DROP DATABASE не работают внутри транзакции — нужен AUTOCOMMIT.
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    quoted = engine.dialect.identifier_preparer.quote(name)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
            if create_again:
                await connection.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        await engine.dispose()


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
    db_settings = base.model_copy(update={"postgres_db": name})
    try:
        asyncio.run(_drop_database(base.database_url, name, create_again=True))
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
    asyncio.run(_drop_database(base.database_url, name, create_again=False))


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
