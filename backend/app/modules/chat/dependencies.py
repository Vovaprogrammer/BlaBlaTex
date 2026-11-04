"""HTTP-часть чата: как разбудить воркер для прогона."""

from typing import Annotated

from fastapi import Depends

from app.modules.chat.tasks import Enqueue, enqueue_run


def get_run_enqueue() -> Enqueue:
    """Как отправить прогон воркеру: задача в очереди Redis. В тестах — подмена."""
    return enqueue_run


RunEnqueue = Annotated[Enqueue, Depends(get_run_enqueue)]
