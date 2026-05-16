import requests
import os
import json
import re
from typing import Optional, Dict, Any, Generator

# Groq API
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in environment variables. Please set it in .env file.")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.1-8b-instant"
FALLBACK_MODELS = ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"]


def get_available_models() -> list:
    return [DEFAULT_MODEL] + FALLBACK_MODELS


def _get_task_config(task: str) -> dict:
    """Возвращает оптимальные настройки для разных типов задач"""
    configs = {
        "document": {"temperature": 0.15, "max_tokens": 4096},
        "formula": {"temperature": 0.05, "max_tokens": 512},
        "part": {"temperature": 0.1, "max_tokens": 2048},
        "math": {"temperature": 0.05, "max_tokens": 2048},
        "explain": {"temperature": 0.3, "max_tokens": 2048},
        "figures": {"temperature": 0.1, "max_tokens": 2048},
    }
    return configs.get(task, {"temperature": 0.3, "max_tokens": 2048})


def _groq_chat(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, task: str = "default", stream: bool = False) -> str:
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    config = _get_task_config(task)
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "max_tokens": config["max_tokens"],
        "temperature": config["temperature"],
        "top_p": 0.95,
        "stream": stream
    }
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            if stream:
                return response
            result = response.json()
            return result["choices"][0]["message"]["content"]
        print(f"Groq API error: {response.status_code}")
        return ""
    except Exception as e:
        print(f"Groq request error: {e}")
        return ""


def _groq_stream_generator(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, task: str = "default") -> Generator[str, None, None]:
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    config = _get_task_config(task)
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "max_tokens": config["max_tokens"],
        "temperature": config["temperature"],
        "top_p": 0.95,
        "stream": True
    }
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=120, stream=True)
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            break
                        try:
                            chunk = json.loads(data)
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                yield f"data: {json.dumps({'token': content})}\n\n"
                        except json.JSONDecodeError:
                            continue
        else:
            yield f"data: {json.dumps({'error': f'HTTP {response.status_code}'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


# ============================================
# GENERATE
# ============================================

def generate_document(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — LaTeX редактор. Создаёшь ТОЛЬКО готовый код. Никаких пояснений."
    user_prompt = f"""Напиши ПОЛНЫЙ LaTeX документ на русском. Тема: {description}
ТРЕБОВАНИЯ:
- \\documentclass{{article}}
- Пакеты: inputenc(utf8), fontenc(T2A), babel(russian), amsmath, amssymb
- Секции: Введение, Основная часть, Заключение
- Фактически верное содержание по теме
- ТОЛЬКО код LaTeX, без markdown"""
    result = _groq_chat(system_prompt, user_prompt, model, task="document")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Выводишь ТОЛЬКО одну формулу LaTeX."
    user_prompt = f"Напиши формулу для: {description}\n\nТОЛЬКО \\[ ... \\], без пояснений."
    result = _groq_chat(system_prompt, user_prompt, model, task="formula")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_part(description: str, part_type: str = "section", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"section": "раздел", "theorem": "теорему с доказательством", "proof": "доказательство", "definition": "определение", "example": "пример"}
    name = names.get(part_type, part_type)
    system_prompt = f"Ты — LaTeX эксперт. Создаёшь {name}. ТОЛЬКО код."
    user_prompt = f"Создай {name}: {description}\n\nТОЛЬКО LaTeX-код, без \\documentclass. Если теорема — полное доказательство."
    result = _groq_chat(system_prompt, user_prompt, model, task="part")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# EXPLAIN
# ============================================

def explain_code(code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — LaTeX эксперт. Объясняешь КРАТКО. НЕ добавляй свой код."
    user_prompt = f"Объясни КРАТКО (2-3 предложения):\n\n{code}\n\nТолько объяснение, без кода."
    result = _groq_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def explain_latex(question: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — учитель LaTeX. Отвечаешь кратко с ОДНИМ примером."
    user_prompt = f"Вопрос: {question}\n\nОтвет: 1-2 предложения + ОДИН пример кода."
    result = _groq_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# MATH
# ============================================

def math_solve_equation(equation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Решаешь уравнения пошагово."
    user_prompt = f"Реши: {equation}\n\nПошаговое решение. Ответ выдели."
    result = _groq_chat(system_prompt, user_prompt, model, task="math")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


def math_derive(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Нахождение производной или интеграла"""
    if operation == "integrate":
        system_prompt = "Ты — эксперт по математическому анализу. Находишь неопределённые интегралы."
        user_prompt = f"Найди интеграл: ∫({expression})dx\n\nПошаговое решение. Ответ выдели. Добавь +C в конце."
    else:
        system_prompt = "Ты — эксперт по математическому анализу. Находишь производные."
        user_prompt = f"Найди производную: d/dx({expression})\n\nПошаговое решение. Ответ выдели."

    result = _groq_chat(system_prompt, user_prompt, model, task="math")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


def math_physics_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — физик. Выводишь формулы."
    user_prompt = f"Задача: {description}\n\nФормула, выражение переменной, шаги, ответ."
    result = _groq_chat(system_prompt, user_prompt, model, task="math")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


def math_check_formula(formula: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Проверяешь формулы."
    user_prompt = f"Проверь: {formula}\n\nСинтаксис, семантика, вердикт, исправление."
    result = _groq_chat(system_prompt, user_prompt, model, task="math")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


# ============================================
# FIGURES
# ============================================

def generate_table(csv_data: str, has_header: bool = True, use_booktabs: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    h = "с заголовками" if has_header else "без заголовков"
    b = "с booktabs" if use_booktabs else "без booktabs"
    system_prompt = "Ты — LaTeX эксперт. Создаёшь таблицы. ТОЛЬКО код."
    user_prompt = f"Создай таблицу ({h}, {b}):\n\n{csv_data}\n\nТолько код таблицы, без \\documentclass."
    result = _groq_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_diagram(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — TikZ эксперт. Создаёшь диаграммы. ТОЛЬКО код."
    user_prompt = f"Создай TikZ: {prompt}\n\nТолько \\begin{{tikzpicture}}...\\end{{tikzpicture}}, без \\documentclass."
    result = _groq_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_plot(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    t = f"Заголовок: {title}\n" if title else ""
    system_prompt = "Ты — pgfplots эксперт. Создаёшь графики. ТОЛЬКО код."
    user_prompt = f"Создай график: {expression}\nX: {xlabel}, Y: {ylabel}\n{t}\nТолько код, без \\documentclass."
    result = _groq_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# REFERENCES
# ============================================

def fetch_bibtex(identifier: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиограф. Генерируешь BibTeX."
    user_prompt = f"Создай BibTeX для: {identifier}\n\nЗаполни: author, title, journal, year, volume, pages, doi. Только BibTeX."
    result = _groq_chat(system_prompt, user_prompt, model, task="references")
    if result:
        result = re.sub(r'```bibtex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def format_references(references: str, style: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"ieee": "IEEE", "gost": "ГОСТ", "apa": "APA"}
    name = names.get(style, style)
    system_prompt = f"Ты — библиограф. Форматируешь по {name}."
    user_prompt = f"Отформатируй по {name}:\n\n{references}\n\nТолько текст."
    result = _groq_chat(system_prompt, user_prompt, model, task="references")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


def check_citation(citation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиограф. Проверяешь ссылки КРАТКО."
    user_prompt = f"Проверь: {citation}\n\nФормат, полнота, исправление (кратко)."
    result = _groq_chat(system_prompt, user_prompt, model, task="references")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


# ============================================
# ACCESSIBILITY
# ============================================

def add_alt_text(figure_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по доступности. Создаёшь alt-текст."
    user_prompt = f"Создай alt (1-2 предложения, СУТЬ):\n\n{figure_code}"
    result = _groq_chat(system_prompt, user_prompt, model, task="accessibility")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


def check_colors(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — колориметрист. Проверяешь цвета."
    user_prompt = f"Проверь: {', '.join(colors)}\n\nСтатус, проблемы, рекомендации (кратко)."
    result = _groq_chat(system_prompt, user_prompt, model, task="accessibility")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


def check_template(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    name = names.get(template, template)
    system_prompt = f"Ты — LaTeX эксперт. Проверяешь {name}."
    user_prompt = f"Проверь на {name}:\n\n{latex_code}\n\nВердикт, проблемы, рекомендации."
    result = _groq_chat(system_prompt, user_prompt, model, task="accessibility")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


# ============================================
# COLLABORATION
# ============================================

def get_diff(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по сравнению. Создаёшь unified diff."
    user_prompt = f"Сравни:\nСтарая: {old_text}\nНовая: {new_text}\n\nФормат: - удалено\n+ добавлено"
    result = _groq_chat(system_prompt, user_prompt, model, task="collaboration")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


def summarize_changes(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — ассистент. Описываешь изменения."
    user_prompt = f"Опиши:\nСтарая: {old_text}\nНовая: {new_text}\n\nДобавлено/Удалено/Изменено."
    result = _groq_chat(system_prompt, user_prompt, model, task="collaboration")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False, "error": "No response"}


def summarize_document(latex_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — редактор. Создаёшь конспекты."
    user_prompt = f"Сделай конспект:\n\n{latex_code}\n\nСохрани структуру и формулы."
    result = _groq_chat(system_prompt, user_prompt, model, task="collaboration")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def fix_latex_errors(code: str, errors: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по LaTeX. Исправляешь ошибки компиляции."
    code_short = code[:3000] if len(code) > 3000 else code
    errors_short = '\n'.join(errors.split('\n')[-100:])
    user_prompt = f"Исправь ошибки компиляции в LaTeX коде.\n\nОшибки:\n{errors_short}\n\nКод:\n{code_short}\n\nВерни ТОЛЬКО исправленный код. Без пояснений."
    result = _groq_chat(system_prompt, user_prompt, model, task="document")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# STREAM FUNCTIONS
# ============================================

def generate_document_stream(description: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator(
        "Ты — LaTeX редактор. Создаёшь ТОЛЬКО готовый код. Никаких пояснений.",
        f"Напиши ПОЛНЫЙ LaTeX документ на русском. Тема: {description}\n\nТРЕБОВАНИЯ:\n- \\documentclass{{article}}\n- Пакеты: inputenc(utf8), fontenc(T2A), babel(russian), amsmath, amssymb\n- Секции: Введение, Основная часть, Заключение\n- Фактически верное содержание\n- ТОЛЬКО код LaTeX, без markdown",
        model, task="document"
    )

def generate_formula_stream(description: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — математик. ТОЛЬКО формула.", f"Формула: {description}\n\nТОЛЬКО \\[ ... \\]", model, task="formula")

def generate_part_stream(description: str, part_type: str = "section", model: str = DEFAULT_MODEL):
    names = {"section": "раздел", "theorem": "теорему с доказательством", "proof": "доказательство", "definition": "определение", "example": "пример"}
    name = names.get(part_type, part_type)
    return _groq_stream_generator(f"Ты — LaTeX эксперт. Создаёшь {name}.", f"Создай {name}: {description}\n\nТОЛЬКО код, без \\documentclass.", model, task="part")

def explain_code_stream(code: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — LaTeX эксперт. Объясняешь КРАТКО.", f"Объясни КРАТКО:\n\n{code}\n\nТолько объяснение, без кода.", model, task="explain")

def explain_latex_stream(question: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — учитель LaTeX.", f"Вопрос: {question}\n\nОтвет: 1-2 предложения + ОДИН пример кода.", model, task="explain")

def math_solve_equation_stream(equation: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — математик.", f"Реши: {equation}\n\nПошагово. Ответ выдели.", model, task="math")


def math_derive_stream(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL):
    """Нахождение производной или интеграла (stream)"""
    if operation == "integrate":
        system_prompt = "Ты — эксперт по математическому анализу. Находишь неопределённые интегралы."
        user_prompt = f"Найди интеграл: ∫({expression})dx\n\nПошаговое решение. Ответ выдели. Добавь +C в конце."
    else:
        system_prompt = "Ты — эксперт по математическому анализу. Находишь производные."
        user_prompt = f"Найди производную: d/dx({expression})\n\nПошаговое решение. Ответ выдели."

    return _groq_stream_generator(system_prompt, user_prompt, model, task="math")

def math_physics_formula_stream(description: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — физик.", f"Задача: {description}\n\nФормула, выражение, шаги, ответ.", model, task="math")

def math_check_formula_stream(formula: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — математик.", f"Проверь: {formula}\n\nСинтаксис, семантика, вердикт.", model, task="math")

def generate_table_stream(csv_data: str, has_header: bool = True, use_booktabs: bool = True, model: str = DEFAULT_MODEL):
    h = "с заголовками" if has_header else "без заголовков"
    b = "с booktabs" if use_booktabs else "без booktabs"
    return _groq_stream_generator("Ты — LaTeX эксперт.", f"Таблица ({h}, {b}):\n\n{csv_data}\n\nТолько код таблицы.", model, task="figures")

def generate_diagram_stream(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — TikZ эксперт.", f"Диаграмма: {prompt}\n\nТолько \\begin{{tikzpicture}}...\\end{{tikzpicture}}.", model, task="figures")

def generate_plot_stream(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "", model: str = DEFAULT_MODEL):
    t = f"Заголовок: {title}\n" if title else ""
    return _groq_stream_generator("Ты — pgfplots эксперт.", f"График: {expression}\nX: {xlabel}, Y: {ylabel}\n{t}\nТолько код.", model, task="figures")

def fetch_bibtex_stream(identifier: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — библиограф.", f"BibTeX для: {identifier}\n\nЗаполни все поля. Только BibTeX.", model, task="references")

def format_references_stream(references: str, style: str = "ieee", model: str = DEFAULT_MODEL):
    names = {"ieee": "IEEE", "gost": "ГОСТ", "apa": "APA"}
    return _groq_stream_generator("Ты — библиограф.", f"Отформатируй по {names.get(style, style)}:\n\n{references}", model, task="references")

def check_citation_stream(citation: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — библиограф.", f"Проверь: {citation}\n\nФормат, полнота, исправление.", model, task="references")

def add_alt_text_stream(figure_code: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — эксперт по доступности.", f"Alt-текст (1-2 предложения):\n\n{figure_code}", model, task="accessibility")

def check_colors_stream(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — колориметрист.", f"Проверь: {', '.join(colors)}\n\nСтатус, проблемы.", model, task="accessibility")

def check_template_stream(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL):
    names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    return _groq_stream_generator("Ты — LaTeX эксперт.", f"Проверь на {names.get(template, template)}:\n\n{latex_code}", model, task="accessibility")

def get_diff_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — эксперт по сравнению.", f"Сравни:\nСтарая: {old_text}\nНовая: {new_text}\n\n- удалено\n+ добавлено", model, task="collaboration")

def summarize_changes_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — ассистент.", f"Опиши:\nСтарая: {old_text}\nНовая: {new_text}", model, task="collaboration")

def summarize_document_stream(latex_code: str, model: str = DEFAULT_MODEL):
    return _groq_stream_generator("Ты — редактор.", f"Конспект:\n\n{latex_code}\n\nСохрани структуру и формулы.", model, task="collaboration")