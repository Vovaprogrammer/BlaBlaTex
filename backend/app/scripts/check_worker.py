"""Проверка старта воркера: ресурсы задач открываются и закрываются так же, как при запуске
(app/worker.py). В сеть проверка не ходит — база, Redis и компилятор не нужны.

CI запускает её в образе воркера: так видно, что в контейнере есть всё, без чего воркер
не стартует, например папка шаблонов.

docker compose run --rm --no-deps worker python -m app.scripts.check_worker
uv run python -m app.scripts.check_worker
"""

import asyncio
import sys

import structlog
from taskiq import TaskiqState

from app.core.config import Settings, get_settings
from app.modules.templates.registry import TemplateError
from app.worker import close_resources, open_resources

logger = structlog.get_logger(__name__)


async def check(settings: Settings) -> int:
    """Открывает и закрывает ресурсы воркера; возвращает, сколько шаблонов он видит."""
    state = TaskiqState()
    await open_resources(state, settings)
    try:
        return len(state.templates)
    finally:
        await close_resources(state)


def main() -> int:
    settings = get_settings()
    try:
        templates = asyncio.run(check(settings))
    except TemplateError as error:
        logger.error("worker_cannot_start", reason=str(error))
        return 1
    logger.info("worker_can_start", templates=templates, templates_dir=str(settings.templates_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
