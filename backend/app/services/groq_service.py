import requests
import os
import json
import re
from typing import Optional, Dict, Any, Generator

# ============================================
# API KEYS & URLS
# ============================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in environment variables. Please set it in .env file.")
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in environment variables. Please set it in .env file.")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ============================================
# MODELS
# ============================================
DEFAULT_MODEL = "llama-3.1-8b-instant"  # Groq - fast, free

OPENROUTER_FREE_MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",  # Best for complex math/code
    "nvidia/nemotron-3-super-120b-a12b:free",  # Huge model, great reasoning
    "meta-llama/llama-3.3-70b-instruct:free",  # Solid all-rounder
]

# Tasks that should use OpenRouter by default
OPENROUTER_TASKS = [
    "document",  # Generate Full Document
    "part",  # Generate Part (all types)
    "math",  # Solve, Derive, Integrate, Physics
    "figures",  # Table, Diagram, Plot
]


def get_available_models() -> list:
    return [
        {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B (Быстрый • Groq)", "tier": "free", "provider": "groq"},
        {"id": "qwen/qwen3-next-80b-a3b-instruct:free", "name": "Qwen 3 Next 80B (Умный • OpenRouter)", "tier": "free",
         "provider": "openrouter"},
        {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "Nemotron 120B (Мощный • OpenRouter)", "tier": "free",
         "provider": "openrouter"},
        {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (Средний • OpenRouter)", "tier": "free",
         "provider": "openrouter"},
    ]


def _get_task_config(task: str) -> dict:
    configs = {
        "document": {"temperature": 0.15, "max_tokens": 4096},
        "formula": {"temperature": 0.05, "max_tokens": 512},
        "part": {"temperature": 0.1, "max_tokens": 2048},
        "math": {"temperature": 0.05, "max_tokens": 2048},
        "explain": {"temperature": 0.3, "max_tokens": 2048},
        "figures": {"temperature": 0.1, "max_tokens": 2048},
    }
    return configs.get(task, {"temperature": 0.3, "max_tokens": 2048})


def _resolve_provider(model: str) -> str:
    if model.startswith("llama-3.1") or model.startswith("mixtral") or model.startswith("gemma2"):
        return "groq"
    return "openrouter"


def _get_api_url(model: str) -> str:
    if _resolve_provider(model) == "groq":
        return GROQ_API_URL
    return OPENROUTER_API_URL


def _get_headers(model: str) -> dict:
    if _resolve_provider(model) == "groq":
        return {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://blablatex.app",
        "X-Title": "BlaBlaTex"
    }


def _clean_markdown(text: str) -> str:
    """Remove Markdown formatting from AI responses for plain text / LaTeX output"""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    text = re.sub(r'```[a-zA-Z]*\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _fix_latex_delimiters(text: str) -> str:
    """Convert LaTeX delimiters to Markdown-compatible for remark-math"""
    text = re.sub(r'\\\[(.*?)\\\]', r'$$\1$$', text, flags=re.DOTALL)
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)
    return text


def _should_use_openrouter(model: str, task: str) -> bool:
    """Determine if OpenRouter should be used based on task and model"""
    if model != DEFAULT_MODEL:
        return _resolve_provider(model) == "openrouter"
    return task in OPENROUTER_TASKS


def _try_openrouter_models(system_prompt: str, user_prompt: str, task: str = "default", stream: bool = False):
    last_error = None
    for model in OPENROUTER_FREE_MODELS:
        try:
            headers = _get_headers(model)
            config = _get_task_config(task)
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": config["max_tokens"],
                "temperature": config["temperature"],
                "top_p": 0.95,
                "stream": stream
            }
            response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
            if response.status_code == 200:
                if stream:
                    return response, model
                result = response.json()
                return result["choices"][0]["message"]["content"], model
            else:
                last_error = f"OpenRouter {model}: HTTP {response.status_code}"
                continue
        except Exception as e:
            last_error = f"OpenRouter {model}: {str(e)}"
            continue
    return None, last_error


def _universal_chat(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, task: str = "default") -> str:
    use_openrouter = _should_use_openrouter(model, task)

    if not use_openrouter:
        # Use Groq
        headers = _get_headers(model)
        config = _get_task_config(task)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": config["max_tokens"],
            "temperature": config["temperature"],
            "top_p": 0.95,
            "stream": False
        }
        try:
            response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=120)
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            return ""
        except Exception as e:
            print(f"Groq error: {e}")
            return ""

    # Use OpenRouter
    effective_model = model if model != DEFAULT_MODEL else OPENROUTER_FREE_MODELS[0]
    headers = _get_headers(effective_model)
    config = _get_task_config(task)
    payload = {
        "model": effective_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": config["max_tokens"],
        "temperature": config["temperature"],
        "top_p": 0.95,
        "stream": False
    }
    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"OpenRouter primary error: {e}")

    # Fallback
    result, error = _try_openrouter_models(system_prompt, user_prompt, task, stream=False)
    if result:
        return result
    print(f"All OpenRouter models failed: {error}")
    return ""


def _universal_stream_generator(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL,
                                task: str = "default") -> Generator[str, None, None]:
    import time
    use_openrouter = _should_use_openrouter(model, task)

    if not use_openrouter:
        # Groq streaming
        headers = _get_headers(model)
        config = _get_task_config(task)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
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
                                yield f"data: {json.dumps({'done': True, 'model': model})}\n\n"
                                break
                            try:
                                chunk = json.loads(data)
                                content = chunk["choices"][0]["delta"].get("content", "")
                                if content:
                                    yield f"data: {json.dumps({'token': content})}\n\n"
                            except json.JSONDecodeError:
                                continue
            else:
                yield f"data: {json.dumps({'error': f'Groq HTTP {response.status_code}'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return

    # OpenRouter: get full response and chunk it
    effective_model = model if model != DEFAULT_MODEL else OPENROUTER_FREE_MODELS[0]
    full_text = _universal_chat(system_prompt, user_prompt, effective_model, task)

    if not full_text:
        yield f"data: {json.dumps({'error': 'All OpenRouter models failed'})}\n\n"
        return

    words = full_text.split(' ')
    buffer = ""
    for i, word in enumerate(words):
        buffer += word
        if i < len(words) - 1:
            buffer += " "
        if len(buffer) >= 15 or i == len(words) - 1:
            yield f"data: {json.dumps({'token': buffer})}\n\n"
            buffer = ""
            time.sleep(0.02)
    yield f"data: {json.dumps({'done': True, 'model': effective_model})}\n\n"


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

    result = _universal_chat(system_prompt, user_prompt, model, task="document")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Выводишь ТОЛЬКО одну формулу LaTeX."
    user_prompt = f"Напиши формулу для: {description}\n\nТОЛЬКО \\[ ... \\], без пояснений."
    result = _universal_chat(system_prompt, user_prompt, model, task="formula")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_part(description: str, part_type: str = "section", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"section": "раздел", "theorem": "теорему с доказательством", "proof": "доказательство",
             "definition": "определение", "example": "пример"}
    name = names.get(part_type, part_type)

    system_prompt = f"Ты — LaTeX эксперт. Создаёшь {name}. ТОЛЬКО код."
    user_prompt = f"Создай {name}: {description}\n\nТОЛЬКО LaTeX-код, без \\documentclass. Если теорема — полное доказательство."

    result = _universal_chat(system_prompt, user_prompt, model, task="part")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# EXPLAIN
# ============================================

def explain_code(code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — LaTeX эксперт. Объясняешь КРАТКО. Используй Markdown для форматирования."
    user_prompt = f"Объясни КРАТКО (2-3 предложения):\n\n{code}\n\nИспользуй **жирный** для ключевых терминов."
    result = _universal_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def explain_latex(question: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — учитель LaTeX. Отвечаешь с примером. Используй Markdown."
    user_prompt = f"Вопрос: {question}\n\nОтвет с примером кода в блоке ```latex."
    result = _universal_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# MATH
# ============================================

def math_solve_equation(equation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Решаешь уравнения пошагово. Используй Markdown для форматирования. Формулы в $...$, ответ **жирным**."
    user_prompt = f"Реши уравнение: {equation}\n\nПиши пошагово, используй Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def math_derive(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    if operation == "integrate":
        system_prompt = "Ты — эксперт по матанализу. Находишь интегралы. Используй Markdown для форматирования. Формулы в $...$, ответ **жирным** + C."
        user_prompt = f"Найди интеграл: ∫({expression})dx\n\nПошаговое решение с Markdown."
    else:
        system_prompt = "Ты — эксперт по матанализу. Находишь производные. Используй Markdown для форматирования. Формулы в $...$, ответ **жирным**."
        user_prompt = f"Найди производную: d/dx({expression})\n\nПошаговое решение с Markdown."

    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def math_physics_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — физик. Выводишь формулы. Используй Markdown для форматирования. Формулы в $...$, ответ **жирным**."
    user_prompt = f"Задача: {description}\n\nВыведи формулу, шаги с Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def math_check_formula(formula: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Проверяешь формулы. Используй Markdown для форматирования. Формулы в $...$."
    user_prompt = f"Проверь формулу: {formula}\n\n**Синтаксис**, **семантика**, **вердикт**, исправление. Используй Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# FIGURES
# ============================================

def generate_table(csv_data: str, has_header: bool = True, use_booktabs: bool = True, model: str = DEFAULT_MODEL) -> \
Dict[str, Any]:
    h = "с заголовками" if has_header else "без заголовков"
    b = "с booktabs" if use_booktabs else "без booktabs"
    system_prompt = "Ты — LaTeX эксперт. Создаёшь таблицы. ТОЛЬКО код."
    user_prompt = f"Создай таблицу ({h}, {b}):\n\n{csv_data}\n\nТолько код таблицы, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_diagram(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — TikZ эксперт. Создаёшь диаграммы. ТОЛЬКО код."
    user_prompt = f"Создай TikZ: {prompt}\n\nТолько \\begin{{tikzpicture}}...\\end{{tikzpicture}}, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_plot(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "", model: str = DEFAULT_MODEL) -> \
Dict[str, Any]:
    t = f"Заголовок: {title}\n" if title else ""
    system_prompt = "Ты — pgfplots эксперт. Создаёшь графики. ТОЛЬКО код."
    user_prompt = f"Создай график: {expression}\nX: {xlabel}, Y: {ylabel}\n{t}\nТолько код, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# REFERENCES
# ============================================

def fetch_bibtex(identifier: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиограф. Генерируешь BibTeX."
    user_prompt = f"Создай BibTeX для: {identifier}\n\nЗаполни: author, title, journal, year, volume, pages, doi. Только BibTeX."
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def format_references(references: str, style: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"ieee": "IEEE", "gost": "ГОСТ", "apa": "APA"}
    name = names.get(style, style)
    system_prompt = f"Ты — библиограф. Форматируешь по {name}."
    user_prompt = f"Отформатируй по {name}:\n\n{references}\n\nТолько отформатированный текст. Никаких пояснений."
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def check_citation(citation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиограф. Проверяешь ссылки. Используй Markdown для форматирования."
    user_prompt = f"Проверь: {citation}\n\n**Формат**, **полнота**, **исправление**. Используй Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# ACCESSIBILITY
# ============================================

def add_alt_text(figure_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по доступности. Создаёшь alt-текст. Только текст, без форматирования."
    user_prompt = f"Создай alt (1-2 предложения, СУТЬ):\n\n{figure_code}\n\nТолько текст, без Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def check_colors(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — колориметрист. Проверяешь цвета. Только текст, без форматирования."
    user_prompt = f"Проверь: {', '.join(colors)}\n\nСтатус, проблемы, рекомендации (кратко). Только текст."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def check_template(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    name = names.get(template, template)
    system_prompt = f"Ты — LaTeX эксперт. Проверяешь {name}. Только текст, без форматирования."
    user_prompt = f"Проверь на {name}:\n\n{latex_code}\n\nВердикт, проблемы, рекомендации. Только текст."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# COLLABORATION
# ============================================

def get_diff(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по сравнению. Создаёшь unified diff. Только текст."
    user_prompt = f"Сравни:\nСтарая: {old_text}\nНовая: {new_text}\n\nФормат: - удалено\n+ добавлено"
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def summarize_changes(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — ассистент. Описываешь изменения. Только текст, без форматирования."
    user_prompt = f"Опиши:\nСтарая: {old_text}\nНовая: {new_text}\n\nДобавлено/Удалено/Изменено. Только текст."
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def summarize_document(latex_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — редактор. Создаёшь конспекты. ТОЛЬКО LaTeX код."
    user_prompt = f"Сделай конспект:\n\n{latex_code}\n\nСохрани структуру и формулы. Только LaTeX код."
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def fix_latex_errors(code: str, errors: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по LaTeX. Исправляешь ошибки компиляции."
    code_short = code[:3000] if len(code) > 3000 else code
    errors_short = '\n'.join(errors.split('\n')[-100:])
    user_prompt = f"Исправь ошибки компиляции в LaTeX коде.\n\nОшибки:\n{errors_short}\n\nКод:\n{code_short}\n\nВерни ТОЛЬКО исправленный код. Без пояснений."
    result = _universal_chat(system_prompt, user_prompt, model, task="document")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# STREAM FUNCTIONS
# ============================================

def generate_document_stream(description: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator(
        "Ты — LaTeX редактор. Создаёшь ТОЛЬКО готовый код. Никаких пояснений.",
        f"Напиши ПОЛНЫЙ LaTeX документ на русском. Тема: {description}\n\nТРЕБОВАНИЯ:\n- \\documentclass{{article}}\n- Пакеты: inputenc(utf8), fontenc(T2A), babel(russian), amsmath, amssymb\n- Секции: Введение, Основная часть, Заключение\n- Фактически верное содержание\n- ТОЛЬКО код LaTeX, без markdown",
        model, task="document"
    )


def generate_formula_stream(description: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — математик. ТОЛЬКО формула.",
                                       f"Формула: {description}\n\nТОЛЬКО \\[ ... \\]", model, task="formula")


def generate_part_stream(description: str, part_type: str = "section", model: str = DEFAULT_MODEL):
    names = {"section": "раздел", "theorem": "теорему с доказательством", "proof": "доказательство",
             "definition": "определение", "example": "пример"}
    name = names.get(part_type, part_type)
    return _universal_stream_generator(f"Ты — LaTeX эксперт. Создаёшь {name}.",
                                       f"Создай {name}: {description}\n\nТОЛЬКО код, без \\documentclass.", model,
                                       task="part")


def explain_code_stream(code: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — LaTeX эксперт. Используй Markdown.",
                                       f"Объясни КРАТКО:\n\n{code}\n\nИспользуй **жирный** для терминов.", model,
                                       task="explain")


def explain_latex_stream(question: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — учитель LaTeX. Используй Markdown.",
                                       f"Вопрос: {question}\n\nОтвет с примером.", model, task="explain")


def math_solve_equation_stream(equation: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — математик. Используй Markdown.",
                                       f"Реши: {equation}\n\nПошагово. Ответ **жирным**.", model, task="math")


def math_derive_stream(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL):
    if operation == "integrate":
        return _universal_stream_generator("Ты — эксперт по матанализу. Используй Markdown.",
                                           f"Интеграл: ∫({expression})dx\n\nПошагово. Ответ **жирным** + C.", model,
                                           task="math")
    return _universal_stream_generator("Ты — эксперт по матанализу. Используй Markdown.",
                                       f"Производная: d/dx({expression})\n\nПошагово. Ответ **жирным**.", model,
                                       task="math")


def math_physics_formula_stream(description: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — физик. Используй Markdown.",
                                       f"Задача: {description}\n\nФормула, шаги, ответ.", model, task="math")


def math_check_formula_stream(formula: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — математик. Используй Markdown.",
                                       f"Проверь: {formula}\n\nСинтаксис, семантика, вердикт.", model, task="math")


def generate_table_stream(csv_data: str, has_header: bool = True, use_booktabs: bool = True,
                          model: str = DEFAULT_MODEL):
    h = "с заголовками" if has_header else "без заголовков"
    b = "с booktabs" if use_booktabs else "без booktabs"
    return _universal_stream_generator("Ты — LaTeX эксперт.",
                                       f"Таблица ({h}, {b}):\n\n{csv_data}\n\nТолько код таблицы.", model,
                                       task="figures")


def generate_diagram_stream(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — TikZ эксперт.",
                                       f"Диаграмма: {prompt}\n\nТолько \\begin{{tikzpicture}}...\\end{{tikzpicture}}.",
                                       model, task="figures")


def generate_plot_stream(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "",
                         model: str = DEFAULT_MODEL):
    t = f"Заголовок: {title}\n" if title else ""
    return _universal_stream_generator("Ты — pgfplots эксперт.",
                                       f"График: {expression}\nX: {xlabel}, Y: {ylabel}\n{t}\nТолько код.", model,
                                       task="figures")


def fetch_bibtex_stream(identifier: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — библиограф.",
                                       f"BibTeX для: {identifier}\n\nЗаполни все поля. Только BibTeX.", model,
                                       task="references")


def format_references_stream(references: str, style: str = "ieee", model: str = DEFAULT_MODEL):
    names = {"ieee": "IEEE", "gost": "ГОСТ", "apa": "APA"}
    return _universal_stream_generator("Ты — библиограф.",
                                       f"Отформатируй по {names.get(style, style)}:\n\n{references}\n\nТолько текст, без пояснений.",
                                       model, task="references")


def check_citation_stream(citation: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — библиограф. Используй Markdown.",
                                       f"Проверь: {citation}\n\nФормат, полнота, исправление.", model,
                                       task="references")


def add_alt_text_stream(figure_code: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — эксперт по доступности.",
                                       f"Alt-текст (1-2 предложения):\n\n{figure_code}\n\nТолько текст.", model,
                                       task="accessibility")


def check_colors_stream(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — колориметрист.", f"Проверь: {', '.join(colors)}\n\nСтатус, проблемы.",
                                       model, task="accessibility")


def check_template_stream(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL):
    names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    return _universal_stream_generator("Ты — LaTeX эксперт.",
                                       f"Проверь на {names.get(template, template)}:\n\n{latex_code}", model,
                                       task="accessibility")


def get_diff_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — эксперт по сравнению.",
                                       f"Сравни:\nСтарая: {old_text}\nНовая: {new_text}\n\n- удалено\n+ добавлено",
                                       model, task="collaboration")


def summarize_changes_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — ассистент.", f"Опиши:\nСтарая: {old_text}\nНовая: {new_text}", model,
                                       task="collaboration")


def summarize_document_stream(latex_code: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — редактор.",
                                       f"Конспект:\n\n{latex_code}\n\nСохрани структуру и формулы. Только LaTeX код.",
                                       model, task="collaboration")