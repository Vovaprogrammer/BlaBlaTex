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
        repeated = current & self.previous
        self.previous = current
        if not repeated and self.failed_builds < MAX_FAILED_BUILDS:
            return
        error = next((e for e in errors if (e.file, e.line, e.message) in repeated), None)
        if error is None and errors:
            error = errors[0]
        reason = "Та же ошибка повторилась" if repeated else "Достигнут предел попыток исправления"
        if error is None:
            detail = "Место ошибки определить не удалось."
        else:
            location = error.file or "неизвестный файл"
            if error.line is not None:
                location += f", строка {error.line}"
            detail = f"{location}: {error.message}"
        raise FixLoopStopped(f"Не удалось собрать отчёт. {reason}. {detail}")
