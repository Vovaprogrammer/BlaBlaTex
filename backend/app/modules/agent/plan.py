"""Заглушка make_plan (architecture.md 9.4), пока план не составляет модель (A3.1).

С ней весь путь «Составить план → план → правка → Подтвердить → отчёт» работает, и фронт
делает панель плана на настоящем API. A3.1 заменяет тело make_plan здесь же, а подключается
он в одном месте — PLANNER в chat/tasks.py.
"""

from decimal import Decimal
from pathlib import PurePosixPath

from app.modules.agent.contract import ModelUsage, PlanRequest, PlanResult
from app.modules.plans.schemas import PlanSection, ReportPlan

STUB_MODEL = "stub"
# Расход заглушки и прогона, который не дошёл до модели.
NO_USAGE = ModelUsage(model=STUB_MODEL, tokens_in=0, tokens_out=0, cost=Decimal(0))
# Разделы шаблона mtuci-lab, куда заглушка кладёт материалы по типу файла.
TASK_SECTION = "task"
WORK_SECTION = "progress"
# Методичка и задание.
TASK_SUFFIXES = frozenset({".pdf", ".docx", ".pptx", ".txt", ".md"})
# Код, вывод программы, данные, скриншоты и ноутбуки — то, что сделал студент.
WORK_SUFFIXES = frozenset(
    {
        *(".py", ".java", ".c", ".cpp", ".h", ".js", ".ts", ".sql", ".go", ".rs", ".kt", ".cs"),
        *(".asm", ".csv", ".json", ".jsonl", ".log", ".yaml", ".yml", ".xml", ".xlsx"),
        *(".png", ".jpg", ".jpeg", ".ipynb"),
    }
)


async def make_plan(request: PlanRequest) -> PlanResult:
    """Разделы шаблона по порядку; методички и задания — в «Задание», код, данные, картинки
    и ноутбуки — в «Ход работы». Остальное и всё, чему нет раздела в шаблоне, — вне плана.
    Модель не вызывает, заметки пустые."""
    usage = NO_USAGE
    if request.cancel.is_set():
        return PlanResult(status="cancelled", usage=usage)
    ids = {section.id for section in request.guide.sections}
    placed: dict[str, list[str]] = {TASK_SECTION: [], WORK_SECTION: []}
    unassigned = []
    for material in request.materials:
        section = _section_for(material.path)
        if section is not None and section in ids:
            placed[section].append(material.path)
        else:
            unassigned.append(material.path)
    sections = [
        PlanSection(
            section_id=section.id,
            title=section.title,
            materials=placed.get(section.id, []),
            note="",
        )
        for section in request.guide.sections
    ]
    plan = ReportPlan(sections=sections, unassigned=unassigned)
    return PlanResult(status="done", plan=plan, usage=usage)


def _section_for(path: str) -> str | None:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in TASK_SUFFIXES:
        return TASK_SECTION
    if suffix in WORK_SUFFIXES:
        return WORK_SECTION
    return None
