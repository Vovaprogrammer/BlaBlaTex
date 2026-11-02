"""Шаблоны через HTTP: список и поля для формы создания проекта."""

from fastapi import FastAPI
from httpx import AsyncClient

from app.modules.templates.dependencies import get_templates

TEMPLATES = "/api/v1/templates"


async def test_list_templates_by_slug(client: AsyncClient) -> None:
    response = await client.get(TEMPLATES)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "slug": "test-lab",
                "version": 1,
                "kind": "lab",
                "title": "Тестовая лабораторная",
                "discipline": "Тестирование & отладка",
            },
            {
                "slug": "test-vkr",
                "version": 2,
                "kind": "vkr",
                "title": "Тестовая ВКР",
                "discipline": None,
            },
        ]
    }


async def test_template_with_fields_and_sections(client: AsyncClient) -> None:
    response = await client.get(f"{TEMPLATES}/test-vkr")

    assert response.status_code == 200
    assert response.json() == {
        "slug": "test-vkr",
        "version": 2,
        "kind": "vkr",
        "title": "Тестовая ВКР",
        "discipline": None,
        "fields": [
            {
                "key": "topic",
                "label": "Тема",
                "type": "text",
                "required": True,
                "default": None,
                "options": [],
            },
            {
                "key": "supervisor",
                "label": "Руководитель",
                "type": "string",
                "required": True,
                "default": None,
                "options": [],
            },
            {
                "key": "degree",
                "label": "Уровень",
                "type": "select",
                "required": False,
                "default": "бакалавр",
                "options": ["бакалавр", "магистр"],
            },
        ],
        "sections": [
            {
                "id": "intro",
                "title": "Введение",
                "file": "chapters/intro.tex",
                "required": True,
                "guide": "Актуальность, цель и задачи.",
            }
        ],
    }


async def test_rules_for_ai_are_not_exposed(client: AsyncClient) -> None:
    response = await client.get(f"{TEMPLATES}/test-lab")

    assert response.status_code == 200
    assert "ai_rules" not in response.json()
    assert "Правило только для агента" not in response.text


async def test_unknown_template_is_not_found(client: AsyncClient) -> None:
    response = await client.get(f"{TEMPLATES}/mtuci-lab")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Шаблон не найден", "details": {}}
    }


async def test_without_templates_list_is_empty(app: FastAPI, client: AsyncClient) -> None:
    # Пустая папка templates/ — не ошибка (реестр тогда пустой, см. test_template_registry).
    app.dependency_overrides[get_templates] = lambda: {}

    response = await client.get(TEMPLATES)

    assert response.status_code == 200
    assert response.json() == {"items": []}
