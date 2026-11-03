"""FakeProjectTools: общий контракт ProjectTools и то, что умеет только фейк."""

from collections.abc import Mapping

import pytest

from app.modules.projects.tools import BuildResult, ProjectTools, ToolError, ToolErrorCode
from tests.fake_project_tools import (
    DEFAULT_GUIDE,
    DEFAULT_PROFILE,
    FakeMaterial,
    FakeProjectTools,
    build_error,
    build_ok,
    latex_error,
)
from tests.project_tools_contract import (
    FILES,
    GENERATED,
    MakeTools,
    ProjectToolsContract,
    expect_error,
)

PNG = b"\x89PNG\r\n\x1a\nfake"


class TestFakeProjectTools(ProjectToolsContract):
    @pytest.fixture
    def make_tools(self) -> MakeTools:
        async def make(
            files: Mapping[str, str], generated: Mapping[str, str] | None = None
        ) -> ProjectTools:
            return FakeProjectTools(files, generated=generated)

        return make


async def test_compile_follows_scenario_and_repeats_last() -> None:
    broken = build_error(latex_error("Undefined control sequence", line=3))
    fixed = build_ok(pages=2)
    tools = FakeProjectTools(FILES, builds=[broken, fixed])
    assert [(await tools.compile()).status for _ in range(3)] == ["error", "ok", "ok"]
    assert (await tools.compile()).pages == 2
    assert tools.calls.count("compile") == 4


async def test_compile_scenario_from_files() -> None:
    def build(fake: FakeProjectTools) -> BuildResult:
        if "\\end{document}" in fake.content("main.tex"):
            return build_ok()
        return build_error(latex_error("Emergency stop", line=4))

    tools = FakeProjectTools({"main.tex": "\\begin{document}\n"}, builds=build)
    assert (await tools.compile()).status == "error"
    await tools.write_file("main.tex", "\\begin{document}\n\\end{document}\n")
    assert (await tools.compile()).status == "ok"


async def test_compile_without_scenario_is_ok() -> None:
    result = await FakeProjectTools(FILES).compile()
    assert (result.status, result.errors, result.warnings_count) == ("ok", [], 0)


def test_build_error_counts_warnings() -> None:
    warning = latex_error("Overfull \\hbox").model_copy(update={"severity": "warning"})
    result = build_error(latex_error("Missing $ inserted"), warning, status="timeout")
    assert (result.status, len(result.errors), result.warnings_count) == ("timeout", 2, 1)


@pytest.fixture
def with_materials() -> FakeProjectTools:
    return FakeProjectTools(
        FILES,
        materials={
            "materials/Методичка.pdf": FakeMaterial(b"%PDF", text="Задание 1. Стек на массиве."),
            "materials/lab.py": FakeMaterial("print(1)\n", text="print(1)\n"),
            "materials/shot.png": FakeMaterial(PNG, description="Вывод программы: 1"),
            "materials/new.docx": FakeMaterial(b"PK", status="pending"),
            "materials/broken.pdf": FakeMaterial(b"%PDF", status="failed"),
        },
    )


async def test_list_materials(with_materials: FakeProjectTools) -> None:
    materials = {item.path: item for item in await with_materials.list_materials()}
    assert set(materials) == {
        "materials/Методичка.pdf",
        "materials/lab.py",
        "materials/shot.png",
        "materials/new.docx",
        "materials/broken.pdf",
    }
    shot = materials["materials/shot.png"]
    assert (shot.mime, shot.size, shot.status) == ("image/png", len(PNG), "ready")
    assert shot.description == "Вывод программы: 1"
    assert materials["materials/new.docx"].status == "pending"
    files = {info.path: info for info in await with_materials.list_files()}
    assert (files["materials/lab.py"].kind, files["materials/lab.py"].role) == ("text", "material")
    assert files["materials/shot.png"].kind == "binary"


async def test_read_material(with_materials: FakeProjectTools) -> None:
    part = await with_materials.read_material("materials/Методичка.pdf", offset=11, limit=4)
    assert (part.text, part.offset, part.total) == ("Стек", 11, 27)
    # Код из материалов читается и построчно, как текстовый файл.
    assert (await with_materials.read_file("materials/lab.py")).text == "1\tprint(1)"


@pytest.mark.parametrize("path", ["materials/new.docx", "materials/broken.pdf"])
async def test_read_material_not_ready(with_materials: FakeProjectTools, path: str) -> None:
    await expect_error(with_materials.read_material(path), ToolErrorCode.MATERIAL_NOT_READY)


@pytest.mark.parametrize("path", ["main.tex", "materials/nope.pdf"])
async def test_read_material_not_found(with_materials: FakeProjectTools, path: str) -> None:
    await expect_error(with_materials.read_material(path), ToolErrorCode.NOT_FOUND)


def test_material_outside_materials_folder() -> None:
    with pytest.raises(ValueError, match="materials/"):
        FakeProjectTools(materials={"lab.py": FakeMaterial("x")})


async def test_get_image() -> None:
    tools = FakeProjectTools(
        FILES, binary={"figures/plot.PNG": PNG, "figures/scheme.svg": b"<svg/>"}
    )
    image = await tools.get_image("figures/plot.PNG")
    assert (image.data, image.mime) == (PNG, "image/png")
    await expect_error(tools.get_image("figures/scheme.svg"), ToolErrorCode.UNSUPPORTED_FILE_TYPE)
    await expect_error(tools.get_image("main.tex"), ToolErrorCode.UNSUPPORTED_FILE_TYPE)
    await expect_error(tools.get_image("figures/none.png"), ToolErrorCode.NOT_FOUND)


async def test_binary_file_is_not_text() -> None:
    tools = FakeProjectTools(FILES, binary={"figures/plot.png": PNG})
    await expect_error(tools.read_file("figures/plot.png"), ToolErrorCode.UNSUPPORTED_FILE_TYPE)
    await expect_error(
        tools.edit_file("figures/plot.png", "a", "b"), ToolErrorCode.UNSUPPORTED_FILE_TYPE
    )
    await expect_error(tools.write_file("figures/plot.png", "x"), ToolErrorCode.ALREADY_EXISTS)
    # В поиске картинок нет.
    assert await tools.search("PNG") == []


async def test_locked_project_rejects_changes_only() -> None:
    tools = FakeProjectTools(FILES, generated=GENERATED)
    tools.locked = True
    await expect_error(tools.write_file("a.tex", "x"), ToolErrorCode.PROJECT_LOCKED)
    await expect_error(tools.edit_file("main.tex", "meta", "x"), ToolErrorCode.PROJECT_LOCKED)
    await expect_error(tools.delete_file("main.tex"), ToolErrorCode.PROJECT_LOCKED)
    assert (await tools.read_file("main.tex")).total_lines == 5
    assert len(await tools.search("input")) == 2


async def test_guide_and_profile() -> None:
    tools = FakeProjectTools(FILES)
    assert await tools.get_template_guide() == DEFAULT_GUIDE
    assert await tools.get_profile() == DEFAULT_PROFILE
    guide = DEFAULT_GUIDE.model_copy(update={"ai_rules": "Только по методичке."})
    assert (
        await FakeProjectTools(guide=guide).get_template_guide()
    ).ai_rules == "Только по методичке."


async def test_calls_and_content_for_assertions() -> None:
    tools = FakeProjectTools(FILES)
    await tools.read_file("main.tex")
    await tools.edit_file("main.tex", "\\input{sections/goal}", "Текст")
    await tools.compile()
    assert tools.calls == ["read_file", "edit_file", "compile"]
    assert "Текст" in tools.content("main.tex")


def test_setup_follows_file_rules() -> None:
    with pytest.raises(ValueError, match="дважды"):
        FakeProjectTools({"meta.tex": "x"}, generated={"meta.tex": "y"})
    with pytest.raises(ToolError, match="latexmkrc"):
        FakeProjectTools({"latexmkrc": "x"})
