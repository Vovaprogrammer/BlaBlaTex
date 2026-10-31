from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переменные из окружения разработчика не должны влиять на тесты настроек."""
    for name in ("APP_ENV", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def write_env(tmp_path: Path, text: str) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return env_file


def test_empty_values_fall_back_to_defaults(tmp_path: Path) -> None:
    settings = Settings(_env_file=write_env(tmp_path, "APP_ENV=\nLOG_LEVEL=\n"))

    assert settings.app_env == "dev"
    assert settings.log_level == "INFO"


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    settings = Settings(_env_file=write_env(tmp_path, "POSTGRES_PASSWORD=x\nAPP_ENV=prod\n"))

    assert settings.app_env == "prod"


def test_log_level_is_case_insensitive(tmp_path: Path) -> None:
    settings = Settings(_env_file=write_env(tmp_path, "LOG_LEVEL=debug\n"))

    assert settings.log_level == "DEBUG"


def test_invalid_log_level_is_validation_error() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level=10)


def test_env_example_is_valid() -> None:
    Settings(_env_file=BACKEND_DIR.parent / ".env.example")
