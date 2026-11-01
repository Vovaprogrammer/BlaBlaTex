"""Логи компилятора: в трейсбеках нет локальных переменных — там бывают куски файлов проекта."""

import pytest
import structlog

from app.logging import configure_logging


def fail_with_project_text_in_locals() -> None:
    # Значение собирается при запуске: в строках исходника, которые показывает трейсбек, его нет.
    text = "-".join(["project", "file", "text"])
    raise ValueError(len(text))


def test_traceback_has_no_local_variables(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    try:
        fail_with_project_text_in_locals()
    except ValueError:
        structlog.get_logger().exception("failed")

    output = capsys.readouterr().out
    assert "ValueError" in output
    assert "project-file-text" not in output
