"""meta.tex (architecture.md 9.6): экранирование, макросы и пересоздание при изменениях."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.models import Profile
from app.modules.projects.models import File
from app.modules.templates.dependencies import get_templates
from app.modules.templates.meta import escape_latex, render_meta
from app.modules.templates.registry import load_templates
from tests.helpers import (
    CSRF,
    STUDENT_EMAIL,
    TEMPLATE_FIXTURES,
    TEST_TEMPLATES,
    CreateProject,
    SignIn,
    SignUp,
)

PROJECTS = "/api/v1/projects"
PROFILE = "/api/v1/profile"
LAB = load_templates(TEMPLATE_FIXTURES)["test-lab"].manifest
# Any — проект как JSON из ответа API.
Json = dict[str, Any]
ELKIN = {
    "last_name": "Ёлкин-Палкин",
    "first_name": "Пётр",
    "middle_name": "Сергеевич",
    "group_name": "БВТ2401",
    "faculty": "Информационные технологии",
    "department": "Математическая кибернетика",
}


def profile(**values: str) -> Profile:
    return Profile(user_id=uuid.uuid4(), **(dict.fromkeys(ELKIN, "") | values))


def test_escapes_tex_special_characters() -> None:
    text = escape_latex("Ёлкин-Палкин & Co_1 #2 {x} ~ ^ \\ %")

    assert text == (
        "Ёлкин-Палкин \\& Co\\_1 \\#2 \\{x\\} \\textasciitilde{} \\textasciicircum{} "
        "\\textbackslash{} \\%"
    )
    assert escape_latex("$5") == "\\$5"


def test_keeps_line_breaks_and_drops_control_characters() -> None:
    assert escape_latex("Цель\r\n\r\nЗадача\rИтог") == "Цель\n\nЗадача\nИтог"
    assert escape_latex("a\x07b\tc\x1bd") == "ab\tcd"


def test_only_text_fields_keep_paragraphs() -> None:
    # Пустая строка — \par, а он ломает, например, \MakeUppercase{\bbtGroup} на титуле.
    vkr = load_templates(TEMPLATE_FIXTURES)["test-vkr"].manifest
    fields = {"topic": "Абзац 1\n\nАбзац 2\n", "supervisor": "Петров\n\nП. П."}

    lines = render_meta(profile(group_name="БВТ\n\n2401 "), vkr, fields).split("\n")

    assert "\\def\\bbtGroup{БВТ 2401}" in lines
    assert "\\def\\bbtSupervisor{Петров П. П.}" in lines
    assert "\\def\\bbtTopic{Абзац 1" in lines
    assert lines[lines.index("\\def\\bbtTopic{Абзац 1") + 2] == "Абзац 2}"


def test_meta_has_profile_template_and_field_macros() -> None:
    meta = render_meta(profile(**ELKIN), LAB, {"lab_number": 3, "lab_title": "Сортировки"})

    assert meta.splitlines()[1:] == [
        "\\def\\bbtLastName{Ёлкин-Палкин}",
        "\\def\\bbtFirstName{Пётр}",
        "\\def\\bbtMiddleName{Сергеевич}",
        "\\def\\bbtShortName{Ёлкин-Палкин~П.~С.}",
        "\\def\\bbtFullName{Ёлкин-Палкин Пётр Сергеевич}",
        "\\def\\bbtGroup{БВТ2401}",
        "\\def\\bbtFaculty{Информационные технологии}",
        "\\def\\bbtDepartment{Математическая кибернетика}",
        "\\def\\bbtDiscipline{Тестирование \\& отладка}",
        "\\def\\bbtYear{\\the\\year}",
        "\\def\\bbtCity{Москва}",
        "\\def\\bbtLabNumber{3}",
        "\\def\\bbtLabTitle{Сортировки}",
        # Необязательное поле без значения — пустой макрос, а не неопределённый.
        "\\def\\bbtVariant{}",
    ]
    assert meta.startswith("% Создаётся автоматически")
    assert meta.endswith("\n")


@pytest.mark.parametrize(
    ("names", "short", "full"),
    [
        ({"last_name": " Иванов ", "first_name": "Иван"}, "Иванов~И.", "Иванов Иван"),
        ({"first_name": "Иван", "middle_name": "Ильич"}, "И.~И.", "Иван Ильич"),
        ({"last_name": "O_Neil", "first_name": "_x"}, "O\\_Neil~\\_.", "O\\_Neil \\_x"),
        ({}, "", ""),
    ],
    ids=["no middle name", "no last name", "special characters", "empty profile"],
)
def test_short_and_full_name(names: dict[str, str], short: str, full: str) -> None:
    lines = render_meta(profile(**names), LAB, {}).splitlines()

    assert f"\\def\\bbtShortName{{{short}}}" in lines
    assert f"\\def\\bbtFullName{{{full}}}" in lines


async def read_meta(client: AsyncClient, project: Json) -> tuple[str, str]:
    """Текст meta.tex проекта и его версия (ETag)."""
    response = await client.get(f"{PROJECTS}/{project['id']}/files/meta.tex")
    assert response.status_code == 200, response.text
    return response.text, response.headers["etag"]


async def test_new_project_gets_meta_from_profile_and_fields(
    user_client: AsyncClient, create_project: CreateProject
) -> None:
    await user_client.put(PROFILE, json=ELKIN)

    project = await create_project("test-lab")

    meta, _ = await read_meta(user_client, project)
    assert meta == render_meta(profile(**ELKIN), LAB, TEST_TEMPLATES["test-lab"])


async def test_profile_change_rewrites_meta_of_own_projects_only(
    user_client: AsyncClient,
    create_project: CreateProject,
    sign_up: SignUp,
    sign_in: SignIn,
) -> None:
    await sign_up("petrov@example.com")
    foreign = await create_project("test-lab")
    await sign_in(STUDENT_EMAIL)
    lab = await create_project("test-lab")
    vkr = await create_project("test-vkr")
    before = (await user_client.get(PROJECTS)).json()["items"]

    response = await user_client.put(PROFILE, json=ELKIN)

    assert response.status_code == 200
    for project in (lab, vkr):
        meta, etag = await read_meta(user_client, project)
        assert "\\def\\bbtShortName{Ёлкин-Палкин~П.~С.}" in meta
        assert etag == '"2"'
    # Правка профиля не поднимает проекты в списке: сам пользователь их не менял.
    assert (await user_client.get(PROJECTS)).json()["items"] == before
    await sign_in("petrov@example.com")
    meta, etag = await read_meta(user_client, foreign)
    assert ("\\def\\bbtLastName{}" in meta, etag) == (True, '"1"')


async def test_same_profile_does_not_bump_meta_version(
    user_client: AsyncClient, create_project: CreateProject
) -> None:
    project = await create_project("test-lab")
    await user_client.put(PROFILE, json=ELKIN)

    await user_client.put(PROFILE, json=ELKIN)

    assert (await read_meta(user_client, project))[1] == '"2"'


async def test_fields_change_rewrites_meta(user_client: AsyncClient, project: Json) -> None:
    url = f"{PROJECTS}/{project['id']}"

    await user_client.patch(url, json={"title": "Другое название"})
    _, after_title = await read_meta(user_client, project)
    await user_client.patch(
        url, json={"fields": {"lab_number": 2, "lab_title": "Поиск & сортировка"}}
    )
    meta, after_fields = await read_meta(user_client, project)

    assert after_title == '"1"'
    assert after_fields == '"2"'
    assert "\\def\\bbtLabNumber{2}" in meta
    assert "\\def\\bbtLabTitle{Поиск \\& сортировка}" in meta


async def test_wrong_fields_leave_meta_unchanged(user_client: AsyncClient, project: Json) -> None:
    response = await user_client.patch(
        f"{PROJECTS}/{project['id']}", json={"fields": {"lab_number": "два"}}
    )

    assert response.status_code == 422
    assert (await read_meta(user_client, project))[1] == '"1"'


async def test_meta_is_read_only_but_still_rewritten(
    user_client: AsyncClient, project: Json
) -> None:
    url = f"{PROJECTS}/{project['id']}"

    responses = [
        await user_client.put(f"{url}/files/meta.tex", content="% правка", headers=CSRF),
        await user_client.delete(f"{url}/files/meta.tex"),
        await user_client.post(f"{url}/move", json={"from": "meta.tex", "to": "my-meta.tex"}),
    ]
    await user_client.put(PROFILE, json=ELKIN)
    await user_client.patch(url, json={"fields": {"lab_number": 2, "lab_title": "Поиск"}})

    assert [r.status_code for r in responses] == [403] * 3
    meta, etag = await read_meta(user_client, project)
    assert etag == '"3"'
    assert "\\def\\bbtGroup{БВТ2401}" in meta
    assert "\\def\\bbtLabNumber{2}" in meta


async def drop_meta(session: AsyncSession, project: Json) -> None:
    """Удаляет meta.tex мимо API — так бывает в проектах до B1.8, тогда его можно было удалить.

    write_generated_file должен справляться и с такими проектами.
    """
    await session.execute(
        delete(File).where(File.project_id == uuid.UUID(project["id"]), File.path == "meta.tex")
    )
    await session.commit()


async def test_deleted_meta_comes_back_on_profile_change(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await drop_meta(db_session, project)

    await user_client.put(PROFILE, json=ELKIN)

    meta, _ = await read_meta(user_client, project)
    assert "\\def\\bbtGroup{БВТ2401}" in meta


async def test_user_file_named_meta_becomes_generated(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await drop_meta(db_session, project)
    # Сгенерированного файла нет — путь свободен, и свой файл записывается.
    await user_client.put(
        f"{PROJECTS}/{project['id']}/files/meta.tex", content="% свой meta.tex", headers=CSRF
    )

    await user_client.put(PROFILE, json=ELKIN)

    tree = (await user_client.get(f"{PROJECTS}/{project['id']}/tree")).json()["items"]
    assert {item["path"]: item["role"] for item in tree}["meta.tex"] == "generated"
    assert "\\def\\bbtGroup{БВТ2401}" in (await read_meta(user_client, project))[0]


async def test_folder_named_meta_does_not_block_profile(
    user_client: AsyncClient, project: Json, db_session: AsyncSession
) -> None:
    await drop_meta(db_session, project)
    await user_client.post(f"{PROJECTS}/{project['id']}/folders", json={"path": "meta.tex"})

    response = await user_client.put(PROFILE, json=ELKIN)

    assert response.status_code == 200
    tree = (await user_client.get(f"{PROJECTS}/{project['id']}/tree")).json()["items"]
    assert {item["path"]: item["kind"] for item in tree}["meta.tex"] == "folder"


async def test_project_of_removed_template_is_skipped(
    app: FastAPI, user_client: AsyncClient, project: Json
) -> None:
    app.dependency_overrides[get_templates] = lambda: {}

    response = await user_client.put(PROFILE, json=ELKIN)

    assert response.status_code == 200
    assert (await read_meta(user_client, project))[1] == '"1"'
