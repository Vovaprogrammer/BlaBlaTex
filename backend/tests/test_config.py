from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переменные из окружения разработчика не должны влиять на тесты настроек."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def write_env(tmp_path: Path, text: str) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return env_file


def test_empty_values_fall_back_to_defaults(tmp_path: Path) -> None:
    settings = Settings(_env_file=write_env(tmp_path, "APP_ENV=\nLOG_LEVEL=\n"))

    assert settings.app_env == "dev"
    assert settings.log_level == "INFO"


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    settings = Settings(_env_file=write_env(tmp_path, "REDIS_PORT=6380\nAPP_ENV=prod\n"))

    assert settings.app_env == "prod"


def test_log_level_is_case_insensitive(tmp_path: Path) -> None:
    settings = Settings(_env_file=write_env(tmp_path, "LOG_LEVEL=debug\n"))

    assert settings.log_level == "DEBUG"


def test_invalid_log_level_is_validation_error() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level=10)


def test_env_example_is_valid() -> None:
    Settings(_env_file=BACKEND_DIR.parent / ".env.example")


def test_database_url_is_built_from_postgres_variables(tmp_path: Path) -> None:
    env = "\n".join(
        [
            "POSTGRES_HOST=db",
            "POSTGRES_PORT=5433",
            "POSTGRES_USER=u",
            "POSTGRES_PASSWORD=p",
            "POSTGRES_DB=d",
        ]
    )
    settings = Settings(_env_file=write_env(tmp_path, env))

    url = settings.database_url

    assert url.render_as_string(hide_password=False) == "postgresql+asyncpg://u:p@db:5433/d"


def test_database_url_escapes_special_characters_in_password() -> None:
    settings = Settings(_env_file=None, postgres_password="p@ss:w/rd%")

    url = settings.database_url

    assert url.password == "p@ss:w/rd%"
    assert "p%40ss%3Aw%2Frd%25" in url.render_as_string(hide_password=False)


def test_password_is_hidden_in_repr() -> None:
    settings = Settings(_env_file=None, postgres_password="top-secret")

    assert "top-secret" not in repr(settings)
    assert "top-secret" not in repr(settings.database_url)
    assert "top-secret" not in str(settings.database_url)


def test_empty_password_means_no_password() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url.password is None
