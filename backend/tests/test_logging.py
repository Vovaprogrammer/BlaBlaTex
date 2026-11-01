"""Логи: в трейсбеках нет локальных переменных — там бывают пароли и тексты пользователей."""

import pytest
import structlog

from app.core.config import Settings
from app.core.logging import configure_logging


def fail_with_secret_in_locals() -> None:
    # Значение собирается при запуске: в строках исходника, которые показывает трейсбек, его нет.
    password = "-".join(["top", "secret", "value"])
    raise RuntimeError(f"длина пароля {len(password)}")


@pytest.mark.parametrize("app_env", ["dev", "prod"])
def test_traceback_has_no_local_variables(app_env: str, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(_env_file=None, app_env=app_env))
    try:
        fail_with_secret_in_locals()
    except RuntimeError:
        structlog.get_logger().exception("failed")
    finally:
        # Настройки structlog глобальные: следующим тестам — настройки по умолчанию.
        structlog.reset_defaults()

    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert "top-secret-value" not in output
