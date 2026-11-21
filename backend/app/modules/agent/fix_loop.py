"""Ограничение последовательных попыток исправления ошибок сборки."""

from app.modules.projects.tools import BuildResult

MAX_FAILED_BUILDS = 4


class FixLoopStopped(Exception):
    """Автоматическое исправление остановлено, объяснение предназначено студенту."""


class FixLoop:
    def __init__(self) -> None:
        self.failed_builds = 0
        self.previous: set[tuple[str | None, int | None, str]] = set()

    def check(self, result: BuildResult) -> None:
        if result.status == "ok":
            self.failed_builds = 0
            self.previous.clear()
            return
        self.failed_builds += 1
        errors = [error for error in result.errors if error.severity == "error"]
        current = {(error.file, error.line, error.message) for error in errors}
        repeated = result.status == "error" and bool(current) and current == self.previous
        self.previous = current if result.status == "error" else set()
        if not repeated and self.failed_builds < MAX_FAILED_BUILDS:
            return
        reason = "Та же ошибка повторилась" if repeated else "Достигнут предел попыток исправления"
        if result.status == "timeout":
            detail = errors[0].message if errors else "Время ожидания сборки истекло."
        elif errors:
            error = errors[0]
            location = error.file or "неизвестный файл"
            if error.line is not None:
                location += f", строка {error.line}"
            detail = f"{location}: {error.message}"
        else:
            detail = "Место ошибки определить не удалось."
        outcome = (
            "Не удалось дождаться результата сборки"
            if result.status == "timeout"
            else "Не удалось собрать отчёт"
        )
        raise FixLoopStopped(f"{outcome}. {reason}. {detail}")
