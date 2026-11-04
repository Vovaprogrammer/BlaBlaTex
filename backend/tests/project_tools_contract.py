"""Общие контрактные тесты ProjectTools (architecture.md 9.4).

Их проходит каждая реализация: фейк (tests/test_fake_project_tools.py) и настоящая
ProjectTools поверх сервисов (tests/test_service_project_tools.py). Чтобы подключить
реализацию, унаследуйте ProjectToolsContract в классе Test... и задайте фикстуру make_tools:
проект с файлами пользователя (role=source, в materials/ — material) и сгенерированными
файлами (role=generated) — как у создания проекта (create_project в сервисе проектов) —
и инструменты для actor из ToolContext.

Тесты проверяют коды ошибок и данные, а не тексты сообщений. Порядок list_files тоже
не проверяется: Postgres сортирует пути по правилам своей локали.
"""

from collections.abc import Awaitable, Mapping
from typing import Protocol

import pytest

from app.modules.projects import service as projects_service
from app.modules.projects.service import TEXT_FILE_MAX_BYTES
from app.modules.projects.tools import Actor, ProjectTools, ToolError, ToolErrorCode

MAIN = (
    "\\documentclass{mtuci-report}\n\\input{meta}\n\\begin{document}\n"
    "\\input{sections/goal}\n\\end{document}\n"
)
GOAL = "Цель работы — изучить списки.\n"
META = "% Создаётся автоматически\n\\def\\bbtGroup{БВТ0000}\n"
FILES = {"main.tex": MAIN, "sections/goal.tex": GOAL}
GENERATED = {"meta.tex": META}


class MakeTools(Protocol):
    def __call__(
        self,
        files: Mapping[str, str],
        generated: Mapping[str, str] | None = None,
        actor: Actor = "ai",
    ) -> Awaitable[ProjectTools]: ...


async def expect_error(call: Awaitable[object], code: ToolErrorCode) -> ToolError:
    with pytest.raises(ToolError) as error:
        await call
    assert error.value.code == code
    return error.value


class ProjectToolsContract:
    """Поведение, одинаковое у всех реализаций ProjectTools."""

    @pytest.fixture
    def make_tools(self) -> MakeTools:
        raise NotImplementedError("Задайте фикстуру make_tools в наследнике")

    @pytest.fixture
    async def tools(self, make_tools: MakeTools) -> ProjectTools:
        return await make_tools(FILES, GENERATED)

    async def versions(self, tools: ProjectTools) -> dict[str, int]:
        return {info.path: info.version for info in await tools.list_files()}

    async def test_follows_protocol(self, tools: ProjectTools) -> None:
        assert isinstance(tools, ProjectTools)

    async def test_list_files_with_folders_and_roles(self, tools: ProjectTools) -> None:
        files = {info.path: info for info in await tools.list_files()}
        assert set(files) == {"main.tex", "meta.tex", "sections", "sections/goal.tex"}
        assert (files["main.tex"].kind, files["main.tex"].role) == ("text", "source")
        assert (files["meta.tex"].kind, files["meta.tex"].role) == ("text", "generated")
        assert (files["sections"].kind, files["sections"].size) == ("folder", 0)
        # Размер — в байтах UTF-8: кириллица по 2 байта.
        assert files["sections/goal.tex"].size == len(GOAL.encode())

    async def test_read_file_numbers_lines(self, tools: ProjectTools) -> None:
        goal = await tools.read_file("sections/goal.tex")
        assert (goal.text, goal.total_lines) == ("1\tЦель работы — изучить списки.", 1)
        assert goal.version == (await self.versions(tools))["sections/goal.tex"]
        part = await tools.read_file("main.tex", 2, 3)
        assert part.text == "2\t\\input{meta}\n3\t\\begin{document}"
        assert (part.start_line, part.end_line, part.total_lines) == (2, 3, 5)

    async def test_read_file_generated_is_allowed(self, tools: ProjectTools) -> None:
        assert (await tools.read_file("meta.tex")).text.startswith("1\t% Создаётся")

    @pytest.mark.parametrize("path", ["nope.tex", "sections"])
    async def test_read_file_missing_or_folder(self, tools: ProjectTools, path: str) -> None:
        await expect_error(tools.read_file(path), ToolErrorCode.NOT_FOUND)

    async def test_read_file_bad_range(self, tools: ProjectTools) -> None:
        await expect_error(tools.read_file("main.tex", 0), ToolErrorCode.VALIDATION_ERROR)
        await expect_error(tools.read_file("main.tex", 3, 2), ToolErrorCode.VALIDATION_ERROR)

    async def test_write_creates_file_and_folders(self, tools: ProjectTools) -> None:
        info = await tools.write_file("sections/extra/notes.tex", "Заметки\n")
        assert (info.path, info.kind, info.role) == ("sections/extra/notes.tex", "text", "source")
        assert info.size == len("Заметки\n".encode())
        files = {info.path: info for info in await tools.list_files()}
        assert files["sections/extra"].kind == "folder"
        assert (await tools.read_file("sections/extra/notes.tex")).text == "1\tЗаметки"

    async def test_new_file_in_materials_is_material(self, make_tools: MakeTools) -> None:
        # Роль задаёт путь (9.8). Писать в materials/ может студент через MCP, но не агент.
        tools = await make_tools(FILES, GENERATED, actor="mcp")
        info = await tools.write_file("materials/notes.txt", "Вывод: 42\n")
        assert info.role == "material"

    async def test_agent_only_reads_materials(self, make_tools: MakeTools) -> None:
        tools = await make_tools({**FILES, "materials/lab.py": "print(1)\n"})

        for change in (
            tools.write_file("materials/notes.txt", "Вывод: 42\n"),
            tools.write_file("materials/lab.py", "print(2)\n"),
            tools.edit_file("materials/lab.py", "1", "2"),
            tools.delete_file("materials/lab.py"),
            tools.delete_file("materials"),
        ):
            await expect_error(change, ToolErrorCode.FORBIDDEN)

        assert (await tools.read_file("materials/lab.py")).text == "1\tprint(1)"
        [material] = await tools.list_materials()
        # Текст материала ещё не извлечён: читать его рано.
        assert (material.path, material.status) == ("materials/lab.py", "pending")
        await expect_error(
            tools.read_material("materials/lab.py"), ToolErrorCode.MATERIAL_NOT_READY
        )

    async def test_write_overwrites_and_version_grows(self, tools: ProjectTools) -> None:
        before = (await self.versions(tools))["main.tex"]
        info = await tools.write_file("main.tex", "новый текст")
        assert info.version > before
        assert (await tools.read_file("main.tex")).text == "1\tновый текст"

    async def test_write_normalizes_path(self, tools: ProjectTools) -> None:
        # «й» из двух символов (так присылает macOS) — тот же файл, что «й» из одного.
        info = await tools.write_file("и\u0306.tex", "x")
        assert info.path == "й.tex"
        assert (await tools.read_file("й.tex")).text == "1\tx"

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "../x.tex",
            "/main.tex",
            ".hidden.tex",
            "a//b.tex",
            "latexmkrc",
            "x%y.tex",
            "a\\b.tex",
        ],
    )
    async def test_write_invalid_path(self, tools: ProjectTools, path: str) -> None:
        await expect_error(tools.write_file(path, "x"), ToolErrorCode.INVALID_PATH)

    async def test_other_methods_check_paths(self, tools: ProjectTools) -> None:
        await expect_error(tools.read_file("../main.tex"), ToolErrorCode.INVALID_PATH)
        await expect_error(tools.edit_file("../main.tex", "a", "b"), ToolErrorCode.INVALID_PATH)
        await expect_error(tools.delete_file("../main.tex"), ToolErrorCode.INVALID_PATH)

    @pytest.mark.parametrize("path", ["run.exe", "figures/plot.png", "Makefile"])
    async def test_write_unsupported_type(self, tools: ProjectTools, path: str) -> None:
        await expect_error(tools.write_file(path, "x"), ToolErrorCode.UNSUPPORTED_FILE_TYPE)

    async def test_write_text_size_limit(self, tools: ProjectTools) -> None:
        # «я» — 2 байта: ровно на пределе можно, на байт больше — нет.
        exact = "я" * (TEXT_FILE_MAX_BYTES // 2)
        assert (await tools.write_file("big.txt", exact)).size == TEXT_FILE_MAX_BYTES
        await expect_error(
            tools.write_file("big.txt", exact + "x"), ToolErrorCode.PAYLOAD_TOO_LARGE
        )

    async def test_write_rejects_nul(self, tools: ProjectTools) -> None:
        await expect_error(tools.write_file("a.tex", "a\x00b"), ToolErrorCode.VALIDATION_ERROR)

    @pytest.mark.parametrize("path", ["sections", "main.tex/x.tex", "meta.tex/x.tex"])
    async def test_write_where_path_is_taken(self, tools: ProjectTools, path: str) -> None:
        await expect_error(tools.write_file(path, "x"), ToolErrorCode.ALREADY_EXISTS)

    async def test_project_size_limit(
        self, tools: ProjectTools, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        used = sum(info.size for info in await tools.list_files())
        monkeypatch.setattr(projects_service, "PROJECT_MAX_BYTES", used + 5)
        await expect_error(tools.write_file("a.tex", "x" * 6), ToolErrorCode.PAYLOAD_TOO_LARGE)
        assert (await tools.write_file("a.tex", "x" * 5)).size == 5

    async def test_generated_file_is_read_only(self, tools: ProjectTools) -> None:
        await expect_error(tools.write_file("meta.tex", "x"), ToolErrorCode.FORBIDDEN)
        await expect_error(tools.edit_file("meta.tex", "БВТ0000", "x"), ToolErrorCode.FORBIDDEN)
        await expect_error(tools.delete_file("meta.tex"), ToolErrorCode.FORBIDDEN)
        assert (await tools.read_file("meta.tex")).total_lines == 2

    async def test_folder_with_generated_file_is_kept(self, make_tools: MakeTools) -> None:
        tools = await make_tools(FILES, {"gen/meta.tex": META})
        await expect_error(tools.delete_file("gen"), ToolErrorCode.FORBIDDEN)
        assert "gen/meta.tex" in await self.versions(tools)

    async def test_edit_replaces_single_occurrence(self, tools: ProjectTools) -> None:
        before = (await self.versions(tools))["main.tex"]
        result = await tools.edit_file("main.tex", "\\input{sections/goal}", "\\input{goal}")
        assert (result.file.path, result.line) == ("main.tex", 4)
        assert result.file.version > before
        assert (await tools.read_file("main.tex", 4, 4)).text == "4\t\\input{goal}"

    async def test_edit_not_found(self, tools: ProjectTools) -> None:
        await expect_error(
            tools.edit_file("main.tex", "нет такого", "x"), ToolErrorCode.EDIT_NOT_FOUND
        )
        assert (await tools.read_file("main.tex")).total_lines == 5

    @pytest.mark.parametrize(("old", "count"), [("\\input", 2), ("{", 5)])
    async def test_edit_not_unique_reports_count(
        self, tools: ProjectTools, old: str, count: int
    ) -> None:
        error = await expect_error(
            tools.edit_file("main.tex", old, "x"), ToolErrorCode.EDIT_NOT_UNIQUE
        )
        assert error.details["count"] == count

    async def test_edit_counts_overlapping(self, make_tools: MakeTools) -> None:
        tools = await make_tools({"a.tex": "ааа"})
        error = await expect_error(
            tools.edit_file("a.tex", "аа", "б"), ToolErrorCode.EDIT_NOT_UNIQUE
        )
        assert error.details["count"] == 2

    async def test_edit_rejects_empty_fragment_and_nul(self, tools: ProjectTools) -> None:
        await expect_error(tools.edit_file("main.tex", "", "x"), ToolErrorCode.VALIDATION_ERROR)
        await expect_error(
            tools.edit_file("main.tex", "\\end{document}", "\x00"), ToolErrorCode.VALIDATION_ERROR
        )

    @pytest.mark.parametrize("path", ["nope.tex", "sections"])
    async def test_edit_missing_or_folder(self, tools: ProjectTools, path: str) -> None:
        await expect_error(tools.edit_file(path, "a", "b"), ToolErrorCode.NOT_FOUND)

    async def test_edit_text_size_limit(self, make_tools: MakeTools) -> None:
        tools = await make_tools({"big.txt": "ab" + "x" * (TEXT_FILE_MAX_BYTES - 2)})
        await expect_error(tools.edit_file("big.txt", "ab", "abc"), ToolErrorCode.PAYLOAD_TOO_LARGE)

    async def test_delete_file(self, tools: ProjectTools) -> None:
        await tools.delete_file("main.tex")
        assert "main.tex" not in await self.versions(tools)
        await expect_error(tools.read_file("main.tex"), ToolErrorCode.NOT_FOUND)

    async def test_delete_folder_with_contents(self, tools: ProjectTools) -> None:
        await tools.delete_file("sections")
        assert set(await self.versions(tools)) == {"main.tex", "meta.tex"}

    async def test_delete_missing(self, tools: ProjectTools) -> None:
        await expect_error(tools.delete_file("nope.tex"), ToolErrorCode.NOT_FOUND)

    async def test_search_ignores_case_across_files(self, tools: ProjectTools) -> None:
        hits = await tools.search("ЦЕЛЬ")
        assert [(hit.path, hit.line, hit.snippet) for hit in hits] == [
            ("sections/goal.tex", 1, "Цель работы — изучить списки."),
        ]
        inputs = await tools.search("\\INPUT")
        assert [(hit.path, hit.line) for hit in inputs] == [("main.tex", 2), ("main.tex", 4)]
        # meta.tex — тоже текстовый файл проекта.
        assert [hit.path for hit in await tools.search("bbtgroup")] == ["meta.tex"]

    async def test_search_limit_and_no_hits(self, tools: ProjectTools) -> None:
        assert [hit.line for hit in await tools.search("{", max_results=2)] == [1, 2]
        assert await tools.search("нет такого") == []

    async def test_search_bad_arguments(self, tools: ProjectTools) -> None:
        await expect_error(tools.search(""), ToolErrorCode.VALIDATION_ERROR)
        await expect_error(tools.search("a", max_results=0), ToolErrorCode.VALIDATION_ERROR)
