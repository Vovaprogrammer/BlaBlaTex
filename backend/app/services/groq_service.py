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

# OpenRouter free models (ordered by capability)
OPENROUTER_FREE_MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",  # Best for complex math/code
    "nvidia/nemotron-3-super-120b-a12b:free",  # Huge model, great reasoning
    "meta-llama/llama-3.3-70b-instruct:free",  # Solid all-rounder
    "google/gemma-3-27b-it:free",  # Good for structured tasks
]

# Mapping tasks to preferred providers
TASK_PROVIDER = {
    "document": "openrouter",  # Complex generation -> OpenRouter
    "math": "openrouter",  # Complex math -> OpenRouter
    "formula": "groq",  # Simple formula -> Groq
    "part": "groq",  # Sections/theorems -> Groq
    "explain": "groq",  # Explanations -> Groq
    "figures": "groq",  # Tables/diagrams -> Groq
    "references": "groq",  # BibTeX -> Groq
    "accessibility": "groq",  # Alt text -> Groq
    "collaboration": "groq",  # Diff/summarize -> Groq
}


def get_available_models() -> list:
    """Returns all available models with metadata"""
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
    """Returns optimal settings for different task types"""
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
    """Determine which API provider to use based on model ID"""
    if model.startswith("llama-3.1") or model.startswith("mixtral") or model.startswith("gemma2"):
        return "groq"
    return "openrouter"


def _get_api_url(model: str) -> str:
    """Get the correct API URL for the model"""
    if _resolve_provider(model) == "groq":
        return GROQ_API_URL
    return OPENROUTER_API_URL


def _get_headers(model: str) -> dict:
    """Get the correct headers for the model"""
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


def _try_openrouter_models(system_prompt: str, user_prompt: str, task: str = "default", stream: bool = False):
    """Try multiple OpenRouter free models until one succeeds"""
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
                print(last_error)
                continue

        except Exception as e:
            last_error = f"OpenRouter {model}: {str(e)}"
            print(last_error)
            continue

    return None, last_error


def _universal_chat(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, task: str = "default") -> str:
    """Unified chat function that routes to Groq or OpenRouter with fallback"""
    provider = _resolve_provider(model)

    # If Groq model, just use Groq directly
    if provider == "groq":
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
            print(f"Groq API error: {response.status_code}")
            return ""
        except Exception as e:
            print(f"Groq request error: {e}")
            return ""

    # If OpenRouter model, try it first, then fallback to other free models
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
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]

        print(f"OpenRouter primary model failed: HTTP {response.status_code}, trying fallbacks...")
    except Exception as e:
        print(f"OpenRouter primary model error: {e}, trying fallbacks...")

    # Fallback: try other free models
    result, error = _try_openrouter_models(system_prompt, user_prompt, task, stream=False)
    if result:
        return result

    print(f"All OpenRouter models failed. Last error: {error}")
    return ""


def _universal_stream_generator(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL,
                                task: str = "default") -> Generator[str, None, None]:
    """Unified streaming generator - real stream for Groq, chunked for OpenRouter"""
    import time

    provider = _resolve_provider(model)
    config = _get_task_config(task)

    # For Groq: use real SSE streaming
    if provider == "groq":
        headers = _get_headers(model)
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

    # For OpenRouter: get full response and chunk it
    # First try the selected model
    full_text = None
    used_model = model

    # Try primary model
    result = _universal_chat(system_prompt, user_prompt, model, task)
    if result:
        full_text = result
    else:
        # Try fallback models
        fallback_result, fallback_model = _try_openrouter_models(system_prompt, user_prompt, task, stream=False)
        if fallback_result:
            full_text = fallback_result
            used_model = fallback_model

    if not full_text:
        yield f"data: {json.dumps({'error': 'All OpenRouter models failed'})}\n\n"
        return

    # Chunk the text and yield with small delays
    words = full_text.split(' ')
    buffer = ""
    for i, word in enumerate(words):
        buffer += word
        if i < len(words) - 1:
            buffer += " "

        # Yield every 2-3 words for smooth effect
        if len(buffer) >= 15 or i == len(words) - 1:
            yield f"data: {json.dumps({'token': buffer})}\n\n"
            buffer = ""
            time.sleep(0.02)  # Tiny delay for visual effect

    yield f"data: {json.dumps({'done': True, 'model': used_model})}\n\n"


# ============================================
# GENERATE
# ============================================

def generate_document(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    # Use smart model selection for complex document generation
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]  # Best free model

    system_prompt = "Ты — LaTeX редактор. Создаёшь ТОЛЬКО готовый код. Никаких пояснений."
    user_prompt = f"""Напиши ПОЛНЫЙ LaTeX документ на русском. Тема: {description}
ТРЕБОВАНИЯ:
- \\documentclass{{article}}
- Пакеты: inputenc(utf8), fontenc(T2A), babel(russian), amsmath, amssymb
- Секции: Введение, Основная часть, Заключение
- Фактически верное содержание по теме
- ТОЛЬКО код LaTeX, без markdown"""

    result = _universal_chat(system_prompt, user_prompt, effective_model, task="document")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": effective_model}
    return {"success": False, "error": "No response"}


def generate_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Выводишь ТОЛЬКО одну формулу LaTeX."
    user_prompt = f"Напиши формулу для: {description}\n\nТОЛЬКО \\[ ... \\], без пояснений."
    result = _universal_chat(system_prompt, user_prompt, model, task="formula")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
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
    result = _universal_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def explain_latex(question: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — учитель LaTeX. Отвечаешь кратко с ОДНИМ примером."
    user_prompt = f"Вопрос: {question}\n\nОтвет: 1-2 предложения + ОДИН пример кода."
    result = _universal_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# MATH
# ============================================

def math_solve_equation(equation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    # Use smart model for complex math
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]

    system_prompt = "Ты — математик. Решаешь уравнения пошагово."
    user_prompt = f"Реши: {equation}\n\nПошаговое решение. Ответ выдели."
    result = _universal_chat(system_prompt, user_prompt, effective_model, task="math")
    return {"success": True, "result": result.strip(), "model": effective_model} if result else {"success": False,
                                                                                                 "error": "No response"}


def math_derive(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    # Use smart model for calculus
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]

    if operation == "integrate":
        system_prompt = "Ты — эксперт по математическому анализу. Находишь неопределённые интегралы."
        user_prompt = f"Найди интеграл: ∫({expression})dx\n\nПошаговое решение. Ответ выдели. Добавь +C в конце."
    else:
        system_prompt = "Ты — эксперт по математическому анализу. Находишь производные."
        user_prompt = f"Найди производную: d/dx({expression})\n\nПошаговое решение. Ответ выдели."

    result = _universal_chat(system_prompt, user_prompt, effective_model, task="math")
    return {"success": True, "result": result.strip(), "model": effective_model} if result else {"success": False,
                                                                                                 "error": "No response"}


def math_physics_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]

    system_prompt = "Ты — физик. Выводишь формулы."
    user_prompt = f"Задача: {description}\n\nФормула, выражение переменной, шаги, ответ."
    result = _universal_chat(system_prompt, user_prompt, effective_model, task="math")
    return {"success": True, "result": result.strip(), "model": effective_model} if result else {"success": False,
                                                                                                 "error": "No response"}


def math_check_formula(formula: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Проверяешь формулы."
    user_prompt = f"Проверь: {formula}\n\nСинтаксис, семантика, вердикт, исправление."
    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


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
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_diagram(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — TikZ эксперт. Создаёшь диаграммы. ТОЛЬКО код."
    user_prompt = f"Создай TikZ: {prompt}\n\nТолько \\begin{{tikzpicture}}...\\end{{tikzpicture}}, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_plot(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "", model: str = DEFAULT_MODEL) -> \
Dict[str, Any]:
    t = f"Заголовок: {title}\n" if title else ""
    system_prompt = "Ты — pgfplots эксперт. Создаёшь графики. ТОЛЬКО код."
    user_prompt = f"Создай график: {expression}\nX: {xlabel}, Y: {ylabel}\n{t}\nТолько код, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
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
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
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
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


def check_citation(citation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиограф. Проверяешь ссылки КРАТКО."
    user_prompt = f"Проверь: {citation}\n\nФормат, полнота, исправление (кратко)."
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


# ============================================
# ACCESSIBILITY
# ============================================

def add_alt_text(figure_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по доступности. Создаёшь alt-текст."
    user_prompt = f"Создай alt (1-2 предложения, СУТЬ):\n\n{figure_code}"
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


def check_colors(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — колориметрист. Проверяешь цвета."
    user_prompt = f"Проверь: {', '.join(colors)}\n\nСтатус, проблемы, рекомендации (кратко)."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


def check_template(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    name = names.get(template, template)
    system_prompt = f"Ты — LaTeX эксперт. Проверяешь {name}."
    user_prompt = f"Проверь на {name}:\n\n{latex_code}\n\nВердикт, проблемы, рекомендации."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


# ============================================
# COLLABORATION
# ============================================

def get_diff(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по сравнению. Создаёшь unified diff."
    user_prompt = f"Сравни:\nСтарая: {old_text}\nНовая: {new_text}\n\nФормат: - удалено\n+ добавлено"
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


def summarize_changes(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — ассистент. Описываешь изменения."
    user_prompt = f"Опиши:\nСтарая: {old_text}\nНовая: {new_text}\n\nДобавлено/Удалено/Изменено."
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
    return {"success": True, "result": result.strip(), "model": model} if result else {"success": False,
                                                                                       "error": "No response"}


def summarize_document(latex_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — редактор. Создаёшь конспекты."
    user_prompt = f"Сделай конспект:\n\n{latex_code}\n\nСохрани структуру и формулы."
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
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
    result = _universal_chat(system_prompt, user_prompt, model, task="document")
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# STREAM FUNCTIONS
# ============================================

def generate_document_stream(description: str, model: str = DEFAULT_MODEL):
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]

    return _universal_stream_generator(
        "Ты — LaTeX редактор. Создаёшь ТОЛЬКО готовый код. Никаких пояснений.",
        f"Напиши ПОЛНЫЙ LaTeX документ на русском. Тема: {description}\n\nТРЕБОВАНИЯ:\n- \\documentclass{{article}}\n- Пакеты: inputenc(utf8), fontenc(T2A), babel(russian), amsmath, amssymb\n- Секции: Введение, Основная часть, Заключение\n- Фактически верное содержание\n- ТОЛЬКО код LaTeX, без markdown",
        effective_model, task="document"
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
    return _universal_stream_generator("Ты — LaTeX эксперт. Объясняешь КРАТКО.",
                                       f"Объясни КРАТКО:\n\n{code}\n\nТолько объяснение, без кода.", model,
                                       task="explain")


def explain_latex_stream(question: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — учитель LaTeX.",
                                       f"Вопрос: {question}\n\nОтвет: 1-2 предложения + ОДИН пример кода.", model,
                                       task="explain")


def math_solve_equation_stream(equation: str, model: str = DEFAULT_MODEL):
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]
    return _universal_stream_generator("Ты — математик.", f"Реши: {equation}\n\nПошагово. Ответ выдели.",
                                       effective_model, task="math")


def math_derive_stream(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL):
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]

    if operation == "integrate":
        system_prompt = "Ты — эксперт по математическому анализу. Находишь неопределённые интегралы."
        user_prompt = f"Найди интеграл: ∫({expression})dx\n\nПошаговое решение. Ответ выдели. Добавь +C в конце."
    else:
        system_prompt = "Ты — эксперт по математическому анализу. Находишь производные."
        user_prompt = f"Найди производную: d/dx({expression})\n\nПошаговое решение. Ответ выдели."

    return _universal_stream_generator(system_prompt, user_prompt, effective_model, task="math")


def math_physics_formula_stream(description: str, model: str = DEFAULT_MODEL):
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]
    return _universal_stream_generator("Ты — физик.", f"Задача: {description}\n\nФормула, выражение, шаги, ответ.",
                                       effective_model, task="math")


def math_check_formula_stream(formula: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — математик.", f"Проверь: {formula}\n\nСинтаксис, семантика, вердикт.",
                                       model, task="math")


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
                                       f"Отформатируй по {names.get(style, style)}:\n\n{references}", model,
                                       task="references")


def check_citation_stream(citation: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — библиограф.", f"Проверь: {citation}\n\nФормат, полнота, исправление.",
                                       model, task="references")


def add_alt_text_stream(figure_code: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — эксперт по доступности.", f"Alt-текст (1-2 предложения):\n\n{figure_code}",
                                       model, task="accessibility")


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
    return _universal_stream_generator("Ты — редактор.", f"Конспект:\n\n{latex_code}\n\nСохрани структуру и формулы.",
                                       model, task="collaboration")