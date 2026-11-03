"""Загрузка файлов через HTTP (architecture.md 9.1, 9.8): роли, замена, лимиты, типы, сборка."""

import hashlib
import io
import unicodedata
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.builds.dependencies import get_compiler
from app.modules.projects import service as projects_service
from tests.fake_compiler import FakeCompiler
from tests.file_samples import DOCX, JPEG, PDF, PNG, PPTX, SVG, XLSX
from tests.helpers import CSRF, SignUp, create_empty_project

# Any — проект и ответы как JSON.
Project = dict[str, Any]
MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nОтчёт\n\\end{document}\n"


def upload_url(project: Project) -> str:
    return f"/api/v1/projects/{project['id']}/upload"


async def upload(
    client: AsyncClient, project: Project, *files: tuple[str, bytes], folder: str = "materials"
) -> Response:
    parts = [("files", (name, data)) for name, data in files]
    return await client.post(upload_url(project), files=parts, data={"dir": folder})


def saved(response: Response) -> dict[str, tuple[str, str, str | None, int]]:
    """Путь → (вид, роль, MIME, размер) из ответа загрузки."""
    assert response.status_code == 200, response.text
    return {
        item["path"]: (item["kind"], item["role"], item["mime"], item["size"])
        for item in response.json()["items"]
    }


def error(response: Response, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()["error"]
    return body


async def tree(client: AsyncClient, project: Project) -> list[str]:
    response = await client.get(f"/api/v1/projects/{project['id']}/tree")
    return [item["path"] for item in response.json()["items"]]


async def text_of(client: AsyncClient, project: Project, path: str) -> str:
    response = await client.get(f"/api/v1/projects/{project['id']}/files/{path}")
    assert response.status_code == 200, response.text
    return response.text


@pytest.fixture
async def project(user_client: AsyncClient, db_session: AsyncSession) -> Project:
    """Пустой проект: без файлов шаблона и meta.tex."""
    me = (await user_client.get("/api/v1/auth/me")).json()
    created = await create_empty_project(db_session, uuid.UUID(me["user"]["id"]))
    return {"id": str(created.id)}


async def test_files_in_materials_become_materials(
    user_client: AsyncClient, project: Project
) -> None:
    code = "// Сортировка\r\nint main() {}\r\n".encode("cp1251")
    stored = "// Сортировка\nint main() {}\n"
    response = await upload(
        user_client,
        project,
        ("scheme.png", PNG),
        ("lab.cpp", code),
        ("method.pdf", PDF),
        ("task.docx", DOCX),
        ("diagram.svg", SVG),
    )

    assert saved(response) == {
        "materials/scheme.png": ("binary", "material", "image/png", len(PNG)),
        # Текст — в UTF-8 и с \n: размер считается после перекодировки.
        "materials/lab.cpp": ("text", "material", "text/plain", len(stored.encode())),
        "materials/method.pdf": ("binary", "material", "application/pdf", len(PDF)),
        "materials/task.docx": (
            "binary",
            "material",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            len(DOCX),
        ),
        "materials/diagram.svg": ("binary", "material", "image/svg+xml", len(SVG)),
    }
    assert await text_of(user_client, project, "materials/lab.cpp") == stored
    assert "materials" in await tree(user_client, project)


async def test_role_follows_path_not_upload_form(
    user_client: AsyncClient, project: Project
) -> None:
    root = await upload(user_client, project, ("scheme.png", PNG), folder="")
    figures = await upload(user_client, project, ("plot.pdf", PDF), folder="figures")
    # Подпапки можно передать в имени файла.
    nested = await upload(user_client, project, ("materials/lab3/out.txt", b"42\n"), folder="")

    assert saved(root)["scheme.png"][1] == "source"
    assert saved(figures)["figures/plot.pdf"][1] == "source"
    assert saved(nested)["materials/lab3/out.txt"][1] == "material"
    assert {"figures", "materials", "materials/lab3"} <= set(await tree(user_client, project))


async def test_same_path_is_replaced_and_version_grows(
    user_client: AsyncClient, project: Project
) -> None:
    first = (await upload(user_client, project, ("lab.py", b"print(1)\n"))).json()["items"][0]
    second = (await upload(user_client, project, ("lab.py", b"print(2)\n"))).json()["items"][0]

    assert (first["version"], second["version"]) == (1, 2)
    assert await text_of(user_client, project, "materials/lab.py") == "print(2)\n"


async def test_file_name_is_normalized_to_nfc(user_client: AsyncClient, project: Project) -> None:
    # macOS присылает «й» двумя символами: «и» и знак краткости.
    name = unicodedata.normalize("NFD", "отчёт_й.png")

    response = await upload(user_client, project, (name, PNG))

    assert list(saved(response)) == ["materials/отчёт_й.png"]


async def test_one_bad_file_rejects_whole_upload(
    user_client: AsyncClient, project: Project
) -> None:
    response = await upload(user_client, project, ("scheme.png", PNG), ("virus.exe", b"MZ"))

    body = error(response, 415)
    assert body["message"].startswith("Файл materials/virus.exe не загрузить")
    assert body["details"] == {"path": "materials/virus.exe"}
    assert await tree(user_client, project) == []


async def test_extension_must_match_content(user_client: AsyncClient, project: Project) -> None:
    response = await upload(user_client, project, ("screen.jpg", PNG))

    body = error(response, 415)
    assert body["message"].endswith("Переименуйте его в screen.png")
    assert body["details"] == {"path": "materials/screen.jpg"}


async def test_binary_content_under_text_extension(
    user_client: AsyncClient, project: Project
) -> None:
    response = await upload(user_client, project, ("notes.txt", JPEG))

    assert error(response, 415)["message"] == (
        "Файл materials/notes.txt — картинка JPEG, а не текст"
    )


async def test_file_size_limits(
    user_client: AsyncClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projects_service, "UPLOAD_FILE_MAX_BYTES", len(PNG) - 1)
    monkeypatch.setattr(projects_service, "TEXT_FILE_MAX_BYTES", 10)

    big = await upload(user_client, project, ("scheme.png", PNG))
    big_text = await upload(user_client, project, ("lab.py", b"print('hello')\n"))
    # В UTF-8 русский текст из cp1251 вдвое длиннее: 6 байт превращаются в 12.
    grown = await upload(user_client, project, ("out.txt", "Привет".encode("cp1251")))

    assert error(big, 413)["details"] == {"path": "materials/scheme.png"}
    assert error(big_text, 413)["message"].startswith("Текстовый файл materials/lab.py больше")
    assert error(grown, 413)["details"] == {"path": "materials/out.txt"}


async def test_order_name_then_type_then_size_then_content(
    user_client: AsyncClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projects_service, "UPLOAD_FILE_MAX_BYTES", 4)

    # Неверный тип видно по имени — размер уже не важен.
    big_exe = await upload(user_client, project, ("setup.exe", b"MZ" * 10))
    # Большой файл не читается: что внутри JPEG, а не PNG, уже не важно.
    big_fake = await upload(user_client, project, ("scheme.png", JPEG))
    # Ошибка в имени второго файла важнее типа первого.
    bad_name = await upload(user_client, project, ("setup.exe", b"MZ"), ("a:b.png", PNG))

    error(big_exe, 415)
    error(big_fake, 413)
    error(bad_name, 422)


async def test_project_size_limit_counts_replaced_files_once(
    user_client: AsyncClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projects_service, "PROJECT_MAX_BYTES", len(PDF) + len(PNG))
    saved(await upload(user_client, project, ("method.pdf", PDF)))

    # Замена того же файла не удваивает его размер.
    replaced = await upload(user_client, project, ("method.pdf", PDF), ("scheme.png", PNG))
    too_much = await upload(user_client, project, ("photo.jpg", JPEG))

    saved(replaced)
    assert error(too_much, 413)["message"].startswith("Проект не может быть больше")
    assert "materials/photo.jpg" not in await tree(user_client, project)


async def test_rejected_upload_leaves_nothing_in_storage(
    app: FastAPI, user_client: AsyncClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projects_service, "PROJECT_MAX_BYTES", len(PNG))

    response = await upload(user_client, project, ("scheme.png", PNG), ("photo.jpg", JPEG))

    error(response, 413)
    # Бинарные файлы пишутся в Storage только после проверок в базе: blob'ов без ссылок нет.
    assert not await app.state.storage.exists(hashlib.sha256(PNG).hexdigest())


async def test_generated_file_cannot_be_replaced(
    user_client: AsyncClient, project: Project, db_session: AsyncSession
) -> None:
    pid = uuid.UUID(project["id"])
    await projects_service.write_generated_file(db_session, pid, "meta.tex", "% meta")
    await db_session.commit()

    response = await upload(user_client, project, ("meta.tex", b"% my meta"), folder="")

    assert error(response, 403)["details"] == {"path": "meta.tex"}


async def test_taken_paths_are_conflicts(user_client: AsyncClient, project: Project) -> None:
    # Папка materials/a.png появляется из пути вложенного файла.
    saved(await upload(user_client, project, ("a.png/b.png", PNG), ("notes.txt", b"2")))

    folder = await upload(user_client, project, ("a.png", PNG))
    file_as_folder = await upload(
        user_client, project, ("x.png", PNG), folder="materials/notes.txt"
    )

    assert error(folder, 409)["details"] == {"path": "materials/a.png"}
    clash = error(file_as_folder, 409)
    assert clash["message"] == "На месте папки materials/notes.txt уже есть файл"
    # В details.path — файл загрузки, которому помешал этот файл.
    assert clash["details"] == {"path": "materials/notes.txt/x.png"}


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        # Полный путь C:\fakepath\… от старых браузеров python-multipart сам сокращает до имени.
        ("lab3\\scheme.png", "символ \\ в пути запрещён"),
        ("../scheme.png", "части пути «.» и «..» запрещены"),
        (".hidden.png", "имя файла или папки не может начинаться с точки"),
    ],
)
async def test_bad_file_name_is_named_in_error(
    user_client: AsyncClient, project: Project, name: str, reason: str
) -> None:
    response = await upload(user_client, project, ("ok.png", PNG), (name, PNG))

    body = error(response, 422)
    assert body["message"].endswith(f": {reason}")
    assert body["details"]["errors"] == [
        {"loc": ["body", "files", 1], "type": "invalid_path", "message": reason}
    ]


async def test_file_without_name() -> None:
    # Через HTTP такой части не прислать: без filename она — поле формы, а не файл.
    nameless = projects_service.IncomingFile("", io.BytesIO(PNG), len(PNG))

    with pytest.raises(AppError) as caught:
        await projects_service.check_uploads("materials", [nameless])

    assert caught.value.message == "Файл «materials/»: у файла нет имени"


async def test_form_part_without_file_name_is_not_a_file(
    user_client: AsyncClient, project: Project
) -> None:
    response = await user_client.post(upload_url(project), files=[("files", (None, "text"))])

    assert error(response, 422)["message"] == "Ожидается файл"


async def test_files_under_other_field_name_are_not_ignored(
    user_client: AsyncClient, project: Project
) -> None:
    response = await user_client.post(upload_url(project), files=[("files[]", ("a.png", PNG))])

    body = error(response, 422)
    assert body["message"] == "Файлы передаются в поле files"
    assert body["details"]["errors"][0]["loc"] == ["body", "files[]"]


async def test_broken_multipart_is_not_reported_as_file_limit(
    user_client: AsyncClient, project: Project
) -> None:
    response = await user_client.post(
        upload_url(project), content=b"x", headers={"Content-Type": "multipart/form-data"}
    )

    assert error(response, 422)["message"] == "Не удалось прочитать файлы из запроса"


async def test_same_path_twice_or_file_as_folder_in_one_upload(
    user_client: AsyncClient, project: Project
) -> None:
    twice = await upload(user_client, project, ("a.png", PNG), ("a.png", PNG))
    both = await upload(user_client, project, ("a.png", PNG), ("a.png/b.png", PNG))

    assert error(twice, 422)["message"] == "Файл «materials/a.png»: файл выбран дважды"
    assert error(both, 422)["details"]["path"] == "materials/a.png"


async def test_form_errors(user_client: AsyncClient, project: Project) -> None:
    no_files = await user_client.post(upload_url(project), files=[("dir", (None, "materials"))])
    not_multipart = await user_client.post(upload_url(project), json={"dir": "materials"})
    bad_dir = await upload(user_client, project, ("a.png", PNG), folder="materials/")

    assert error(no_files, 422)["message"] == "Выберите файлы для загрузки"
    assert error(not_multipart, 422)["details"]["errors"][0]["loc"] == ["header", "content-type"]
    bad_dir_error = error(bad_dir, 422)
    assert bad_dir_error["message"].startswith("Папка «materials/»:")
    assert bad_dir_error["details"]["errors"][0]["loc"] == ["body", "dir"]


async def test_too_many_files(
    user_client: AsyncClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projects_service, "UPLOAD_MAX_FILES", 2)

    response = await upload(user_client, project, *[(f"{n}.txt", b"x") for n in range(3)])

    assert "не больше 2 файлов" in error(response, 422)["message"]


async def test_request_size_limit(
    user_client: AsyncClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projects_service, "UPLOAD_REQUEST_MAX_BYTES", 1000)
    boundary = "bbt-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="big.txt"\r\n'
        f"\r\n{'x' * 2000}\r\n--{boundary}--\r\n"
    ).encode()

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 100):
            yield body[start : start + 100]

    content_type = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    # Без Content-Length (поток кусками) запрос обрывается, когда пришло больше лимита.
    streamed = await user_client.post(upload_url(project), content=chunks(), headers=content_type)
    # С Content-Length — сразу, ещё до чтения.
    declared = await user_client.post(upload_url(project), content=body, headers=content_type)

    assert "content-length" not in streamed.request.headers
    assert error(streamed, 413)["message"].startswith("За один раз можно загрузить до")
    error(declared, 413)


async def test_needs_session_and_own_project(
    user_client: AsyncClient, project: Project, sign_up: SignUp
) -> None:
    await sign_up("other@example.com")
    foreign = await upload(user_client, project, ("a.png", PNG))
    user_client.cookies.clear()
    anonymous = await upload(user_client, project, ("a.png", PNG))

    error(foreign, 404)
    error(anonymous, 401)


async def test_binary_file_keeps_its_type_when_renamed(
    user_client: AsyncClient, project: Project
) -> None:
    saved(await upload(user_client, project, ("photo.jpg", JPEG), ("scheme.png", PNG)))
    move_url = f"/api/v1/projects/{project['id']}/move"

    to_jpeg = await user_client.post(
        move_url, json={"from": "materials/photo.jpg", "to": "materials/photo.jpeg"}
    )
    to_pdf = await user_client.post(
        move_url, json={"from": "materials/scheme.png", "to": "materials/scheme.pdf"}
    )
    to_text = await user_client.post(
        move_url, json={"from": "materials/scheme.png", "to": "materials/scheme.txt"}
    )

    assert to_jpeg.status_code == 200, to_jpeg.text
    assert error(to_pdf, 415)["message"].startswith("Файл materials/scheme.png не переименовать")
    error(to_text, 415)


async def test_binary_file_cannot_be_written_as_text(
    user_client: AsyncClient, project: Project
) -> None:
    saved(await upload(user_client, project, ("scheme.png", PNG)))

    response = await user_client.put(
        f"/api/v1/projects/{project['id']}/files/materials/scheme.png", content=b"text"
    )

    assert error(response, 415)["message"].startswith("Файл materials/scheme.png не сохранить")


async def test_build_gets_images_and_code_from_materials_but_not_documents(
    app: FastAPI, user_client: AsyncClient, project: Project
) -> None:
    fake = FakeCompiler()
    compiler = fake.client()
    app.dependency_overrides[get_compiler] = lambda: compiler
    await user_client.put(f"/api/v1/projects/{project['id']}/files/main.tex", content=MAIN_TEX)
    saved(
        await upload(
            user_client,
            project,
            ("scheme.png", PNG),
            ("photo.jpg", JPEG),
            ("lab.py", b"print(1)\n"),
            ("method.pdf", PDF),
            ("task.docx", DOCX),
            ("slides.pptx", PPTX),
            ("data.xlsx", XLSX),
        )
    )

    response = await user_client.post(f"/api/v1/projects/{project['id']}/builds", headers=CSRF)

    assert response.status_code == 202, response.text
    [request] = fake.requests
    # Документы из материалов читает только ИИ (architecture.md 6).
    assert request.files() == {
        "main.tex": MAIN_TEX.encode(),
        "materials/scheme.png": PNG,
        "materials/photo.jpg": JPEG,
        "materials/lab.py": b"print(1)\n",
    }


# Скачивание: GET /files/{path}.


async def download(client: AsyncClient, project: Project, path: str) -> Response:
    return await client.get(f"/api/v1/projects/{project['id']}/files/{path}")


@pytest.mark.parametrize(
    ("name", "data", "mime"),
    [
        ("scheme.png", PNG, "image/png"),
        ("photo.jpeg", JPEG, "image/jpeg"),
        ("method.pdf", PDF, "application/pdf"),
        (
            "data.xlsx",
            XLSX,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
async def test_binary_file_is_served_with_its_type(
    user_client: AsyncClient, project: Project, name: str, data: bytes, mime: str
) -> None:
    saved(await upload(user_client, project, (name, data)))

    response = await download(user_client, project, f"materials/{name}")

    assert response.status_code == 200, response.text
    assert response.content == data
    assert response.headers["Content-Type"] == mime
    assert response.headers["Content-Length"] == str(len(data))
    assert response.headers["ETag"] == '"1"'
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Disposition"] == (
        f"inline; filename=\"{name}\"; filename*=UTF-8''{name}"
    )
    assert "Content-Security-Policy" not in response.headers


async def test_svg_is_sandboxed(user_client: AsyncClient, project: Project) -> None:
    saved(await upload(user_client, project, ("diagram.svg", SVG)))

    response = await download(user_client, project, "materials/diagram.svg")

    assert response.headers["Content-Type"] == "image/svg+xml"
    assert response.headers["Content-Security-Policy"] == "sandbox"


async def test_russian_file_name_is_kept_for_save_as(
    user_client: AsyncClient, project: Project
) -> None:
    saved(await upload(user_client, project, ("Отчёт ЛР 3.pdf", PDF), ("код.py", b"x = 1\n")))

    binary = await download(user_client, project, "materials/Отчёт ЛР 3.pdf")
    text = await download(user_client, project, "materials/код.py")

    assert binary.headers["Content-Disposition"] == (
        'inline; filename="_____ __ 3.pdf"; '
        "filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82%20%D0%9B%D0%A0%203.pdf"
    )
    assert text.headers["Content-Disposition"].startswith('inline; filename="___.py"')
    assert text.headers["Content-Type"] == "text/plain; charset=utf-8"


async def test_lost_blob_is_404(app: FastAPI, user_client: AsyncClient, project: Project) -> None:
    saved(await upload(user_client, project, ("scheme.png", PNG)))
    await app.state.storage.delete(hashlib.sha256(PNG).hexdigest())

    response = await download(user_client, project, "materials/scheme.png")

    assert error(response, 404)["message"] == "Содержимое файла потеряно. Загрузите его ещё раз."


async def test_deleted_file_keeps_its_blob(
    app: FastAPI, user_client: AsyncClient, project: Project
) -> None:
    saved(await upload(user_client, project, ("scheme.png", PNG)))

    response = await user_client.delete(f"/api/v1/projects/{project['id']}/files/materials")

    assert response.status_code == 204
    # На blob сошлются ревизии (B2.5); неиспользуемые удаляет очистка хранилища (B3.3).
    assert await app.state.storage.exists(hashlib.sha256(PNG).hexdigest())
