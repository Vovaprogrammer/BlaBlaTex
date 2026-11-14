"""Инструменты PydanticAI поверх проектных сервисов."""

from collections.abc import Awaitable, Callable

from pydantic_ai import Agent, BinaryContent, RunContext, ToolReturn

from app.modules.agent.contract import RunRequest
from app.modules.projects.tools import DEFAULT_MATERIAL_LIMIT, DEFAULT_MAX_RESULTS, ToolError


async def _call[T](
    ctx: RunContext[RunRequest],
    operation: Callable[[], Awaitable[T]],
    summary: str,
) -> T | str:
    name, call_id = ctx.tool_name, ctx.tool_call_id
    assert name is not None and call_id is not None
    if ctx.deps.cancel.is_set():
        return "Прогон отменён."
    await ctx.deps.events.tool_call(call_id, name, summary)
    if ctx.deps.cancel.is_set():
        await ctx.deps.events.tool_result(call_id, False, "Прогон отменён.")
        return "Прогон отменён."
    try:
        result = await operation()
    except ToolError as error:
        await ctx.deps.events.tool_result(call_id, False, error.message)
        return error.message
    await ctx.deps.events.tool_result(call_id, True, "Готово")
    return result


def register_tools(agent: Agent[RunRequest, str]) -> None:
    # Инструментам без параметров модели часто передают лишнее, например {"path": "."}.
    # Без **_ignored это ошибка проверки, и после повторов прогон падает целиком, хотя
    # лишний параметр ни на что не влияет. Поэтому такие инструменты его пропускают.
    @agent.tool
    async def list_files(ctx: RunContext[RunRequest], **_ignored: object) -> object:
        """Показать дерево файлов и папок проекта."""
        return await _call(ctx, ctx.deps.tools.list_files, "Список файлов")

    @agent.tool
    async def read_file(
        ctx: RunContext[RunRequest],
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> object:
        """Прочитать текст файла по пути от корня. Номера строк начинаются с 1."""
        return await _call(
            ctx, lambda: ctx.deps.tools.read_file(path, start_line, end_line), f"Чтение {path}"
        )

    @agent.tool
    async def search(
        ctx: RunContext[RunRequest], query: str, max_results: int = DEFAULT_MAX_RESULTS
    ) -> object:
        """Найти строки текстовых файлов по подстроке без учёта регистра."""
        return await _call(
            ctx, lambda: ctx.deps.tools.search(query, max_results), "Поиск по файлам"
        )

    @agent.tool(sequential=True)
    async def write_file(ctx: RunContext[RunRequest], path: str, content: str) -> object:
        """Создать текстовый файл или записать в него полное содержимое."""
        return await _call(ctx, lambda: ctx.deps.tools.write_file(path, content), f"Запись {path}")

    @agent.tool(sequential=True)
    async def edit_file(ctx: RunContext[RunRequest], path: str, old: str, new: str) -> object:
        """Заменить точный фрагмент old на new. Фрагмент должен встречаться ровно один раз."""
        return await _call(ctx, lambda: ctx.deps.tools.edit_file(path, old, new), f"Правка {path}")

    @agent.tool(sequential=True)
    async def delete_file(ctx: RunContext[RunRequest], path: str) -> object:
        """Удалить файл или папку со всем её содержимым."""
        return await _call(ctx, lambda: ctx.deps.tools.delete_file(path), f"Удаление {path}")

    @agent.tool(sequential=True)
    async def compile(ctx: RunContext[RunRequest], **_ignored: object) -> object:
        """Собрать отчёт в PDF и вернуть статус сборки и диагностику."""
        return await _call(ctx, ctx.deps.tools.compile, "Сборка PDF")

    @agent.tool(sequential=True)
    async def run_checks(ctx: RunContext[RunRequest], **_ignored: object) -> object:
        """Проверить отчёт и получить находки и состояние проверки PDF."""
        return await _call(ctx, ctx.deps.tools.run_checks, "Проверка отчёта")

    @agent.tool
    async def list_materials(ctx: RunContext[RunRequest], **_ignored: object) -> object:
        """Показать загруженные материалы и готовность извлечённого текста."""
        return await _call(ctx, ctx.deps.tools.list_materials, "Список материалов")

    @agent.tool
    async def read_material(
        ctx: RunContext[RunRequest], path: str, offset: int = 0, limit: int = DEFAULT_MATERIAL_LIMIT
    ) -> object:
        """Прочитать извлечённый текст материала. Смещение и лимит задаются в символах."""
        return await _call(
            ctx, lambda: ctx.deps.tools.read_material(path, offset, limit), f"Материал {path}"
        )

    @agent.tool
    async def get_image(ctx: RunContext[RunRequest], path: str) -> ToolReturn[str] | str:
        """Посмотреть загруженное изображение PNG или JPEG."""
        image = await _call(ctx, lambda: ctx.deps.tools.get_image(path), f"Изображение {path}")
        if isinstance(image, str):
            return image
        return ToolReturn(
            return_value="Изображение приложено.",
            content=[BinaryContent(data=image.data, media_type=image.mime)],
        )

    @agent.tool
    async def get_template_guide(ctx: RunContext[RunRequest], **_ignored: object) -> object:
        """Получить разделы, правила, поля и макросы текущего шаблона."""
        return await _call(ctx, ctx.deps.tools.get_template_guide, "Руководство по шаблону")

    @agent.tool
    async def get_profile(ctx: RunContext[RunRequest], **_ignored: object) -> object:
        """Получить учебный профиль владельца проекта."""
        return await _call(ctx, ctx.deps.tools.get_profile, "Учебный профиль")
