"""Заглушка run_agent (architecture.md 9.4), пока нет настоящего агента (A2.1).

С ней весь путь «сообщение → прогон → ответ → события» работает, и фронт делает чат на
настоящем API. A2.1 подключает агента в одном месте — импорт run_agent в chat/tasks.py.
"""

from decimal import Decimal

from app.modules.agent.contract import ModelUsage, RunRequest, RunResult

STUB_MODEL = "stub"
STUB_REPLY = "ИИ-агент ещё не подключён. Скоро он сможет делать отчёты по вашим материалам."


async def run_agent(request: RunRequest) -> RunResult:
    """Сразу отвечает, что агента ещё нет: файлы не меняет, модель не вызывает."""
    return RunResult(
        status="done",
        text=STUB_REPLY,
        usage=ModelUsage(model=STUB_MODEL, tokens_in=0, tokens_out=0, cost=Decimal(0)),
    )
