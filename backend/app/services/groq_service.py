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
DEFAULT_MODEL = "llama-3.1-8b-instant"

OPENROUTER_FREE_MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

OPENROUTER_TASKS = ["document", "part", "math", "figures"]


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

    if part_type == "theorem":
        system_prompt = "Ты — LaTeX эксперт. Создаёшь теорему с доказательством. ТОЛЬКО код. Обязательно добавь: \\usepackage{amsthm} и \\newtheorem{theorem}{Теорема}."
        user_prompt = f"Сформулируй и докажи теорему: {description}\n\nОбязательно включи:\n1. \\usepackage{{amsthm}}\n2. \\newtheorem{{theorem}}{{Теорема}}\n3. \\begin{{theorem}}...\\end{{theorem}}\n4. \\begin{{proof}}...\\end{{proof}}\n\nТОЛЬКО эти окружения, без \\documentclass."
    elif part_type == "proof":
        system_prompt = "Ты — LaTeX эксперт. Создаёшь доказательство. ТОЛЬКО код. Обязательно добавь: \\usepackage{amsthm}."
        user_prompt = f"Докажи: {description}\n\nОбязательно включи:\n1. \\usepackage{{amsthm}}\n2. \\begin{{proof}}...\\end{{proof}}\n\nТОЛЬКО proof, без \\documentclass."
    else:
        system_prompt = f"Ты — LaTeX эксперт. Создаёшь {name}. ТОЛЬКО код."
        user_prompt = f"Создай {name}: {description}\n\nТОЛЬКО LaTeX-код, без \\documentclass."

    result = _universal_chat(system_prompt, user_prompt, model, task="part")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# EXPLAIN
# ============================================

def explain_code(code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — LaTeX эксперт. Сначала объясни ОБЩИЙ СМЫСЛ кода (1-2 предложения). Затем разбери КАЖДУЮ функцию/команду отдельно. Используй Markdown."
    user_prompt = f"Объясни этот LaTeX-код:\n\n{code}\n\n1. Общий смысл (1-2 предложения)\n2. Разбор КАЖДОЙ команды: что делает и зачем\nИспользуй **жирный** для названий команд."
    result = _universal_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def explain_latex(question: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — учитель LaTeX. Отвечаешь с примером. Используй Markdown."
    user_prompt = f"Вопрос: {question}\n\nОтвет с примером кода в блоке ```latex. Объясни, КАК это работает."
    result = _universal_chat(system_prompt, user_prompt, model, task="explain")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# MATH
# ============================================

def math_solve_equation(equation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Решаешь уравнения пошагово. Используй Markdown. ВСЕ формулы заворачивай в $...$ (inline) или $$...$$ (display). Никаких \[...\] или \(...\). Ответ выделяй **жирным**."
    user_prompt = f"Реши уравнение: {equation}\n\nПиши пошагово, используй Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def math_derive(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    if operation == "integrate":
        system_prompt = "Ты — эксперт по матанализу. Находишь интегралы. Используй Markdown. ВСЕ формулы в $...$ или $$...$$. Никаких \[...\] или \(...\). Ответ **жирным** + C."
        user_prompt = f"Найди интеграл: ∫({expression})dx\n\nПошаговое решение с Markdown."
    else:
        system_prompt = "Ты — эксперт по матанализу. Находишь производные. Используй Markdown. ВСЕ формулы в $...$ или $$...$$. Никаких \[...\] или \(...\). Ответ **жирным**."
        user_prompt = f"Найди производную: d/dx({expression})\n\nПошаговое решение с Markdown."

    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def math_physics_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — физик. Выводишь формулы. Используй Markdown. ВСЕ формулы в $...$ или $$...$$. Никаких \[...\] или \(...\). Ответ **жирным**."
    user_prompt = f"Задача: {description}\n\nВыведи формулу, шаги с Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def math_check_formula(formula: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математик. Проверяешь формулы. Используй Markdown. ВСЕ формулы в $...$ или $$...$$. Никаких \[...\] или \(...\)."
    user_prompt = f"Проверь формулу: {formula}\n\n**Синтаксис**, **семантика**, **вердикт**, исправление. Используй Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="math")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# FIGURES
# ============================================

def generate_table(csv_data: str, has_header: bool = True, use_booktabs: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    h = "с заголовками" if has_header else "без заголовков"
    b = "с booktabs" if use_booktabs else "без booktabs"
    system_prompt = "Ты — LaTeX эксперт. Создаёшь таблицы. ТОЛЬКО код."
    user_prompt = f"Создай таблицу ({h}, {b}):\n\n{csv_data}\n\nОбязательно включи:\n1. \\usepackage{{booktabs}}\n2. \\begin{{tabular}}...\\end{{tabular}} с \\toprule, \\midrule, \\bottomrule\n\nТолько код таблицы, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_diagram(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — TikZ эксперт. Создаёшь диаграммы. ТОЛЬКО код."
    user_prompt = f"Создай TikZ диаграмму: {prompt}\n\nОбязательно включи:\n1. \\usepackage{{tikz}}\n2. \\begin{{tikzpicture}}...\\end{{tikzpicture}}\n\nТолько код, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def generate_plot(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    t = f"Заголовок: {title}\n" if title else ""
    system_prompt = "Ты — pgfplots эксперт. Создаёшь графики. ТОЛЬКО код."
    user_prompt = f"Создай график: {expression}\nX: {xlabel}, Y: {ylabel}\n{t}\nОбязательно включи:\n1. \\usepackage{{pgfplots}}\n2. \\begin{{tikzpicture}}\n3. \\begin{{axis}}...\\end{{axis}}\n4. \\end{{tikzpicture}}\n\nТолько код, без \\documentclass."
    result = _universal_chat(system_prompt, user_prompt, model, task="figures")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# REFERENCES
# ============================================

def fetch_bibtex(identifier: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиограф. Генерируешь BibTeX с реальными данными."
    user_prompt = f"Создай BibTeX для: {identifier}\n\nЗаполни ВСЕ поля реальными данными: author, title, journal, year, volume, pages, doi. Только BibTeX."
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def format_references(references: str, style: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"ieee": "IEEE", "gost": "ГОСТ", "apa": "APA"}
    name = names.get(style, style)
    system_prompt = f"Ты — библиограф. Форматируешь по {name}. Только отформатированный текст."
    user_prompt = f"Отформатируй по {name}:\n\n{references}\n\nТолько отформатированный текст. Никаких пояснений, никаких кодовых блоков."
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def check_citation(citation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиограф. Проверяешь ссылки. Используй Markdown. НЕ выдумывай данные, которых нет в оригинале."
    user_prompt = f"Проверь: {citation}\n\n**Формат**, **полнота**, **исправление** (только если есть ошибки, не добавляй лишнего). Используй Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="references")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# ACCESSIBILITY
# ============================================

def add_alt_text(figure_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по доступности. Создаёшь подробный alt-текст. Используй Markdown."
    user_prompt = f"Создай alt-текст (3-4 предложения) для этого изображения:\n\n{figure_code}\n\nОпиши:\n1. **Тип** графика/диаграммы\n2. **Оси** и что на них\n3. **Что изображено** (цвета, форма, тренд)\n4. **Ключевая информация**\n\nИспользуй **жирный** для важных деталей."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def check_colors(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — колориметрист. Проверяешь цвета. Используй Markdown."
    user_prompt = f"Проверь: {', '.join(colors)}\n\n**Контрастность**, **дальтонизм**, **рекомендации**. Markdown."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def check_template(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    name = names.get(template, template)
    system_prompt = f"Ты — LaTeX эксперт. Проверяешь {name}. Только вердикт и проблемы. НЕ добавляй лишних команд. Используй Markdown."
    user_prompt = f"Проверь на {name}:\n\n{latex_code}\n\n**Вердикт**, **проблемы** (кратко). Markdown. Не добавляй новых команд."
    result = _universal_chat(system_prompt, user_prompt, model, task="accessibility")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


# ============================================
# COLLABORATION
# ============================================

def get_diff(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по сравнению. Создаёшь unified diff. Используй Markdown."
    user_prompt = f"Сравни:\nСтарая: {old_text}\nНовая: {new_text}\n\nФормат Markdown:\n- Удалено: ...\n+ Добавлено: ...\nИспользуй **жирный** для ключевых изменений."
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def summarize_changes(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — ассистент. Описываешь изменения. Используй Markdown."
    user_prompt = f"Опиши изменения:\nСтарая: {old_text}\nНовая: {new_text}\n\nФормат Markdown. **Добавлено**, *удалено*, ***изменено***."
    result = _universal_chat(system_prompt, user_prompt, model, task="collaboration")
    if result:
        result = _fix_latex_delimiters(result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response"}


def summarize_document(latex_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    # Force OpenRouter for this complex task
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]

    system_prompt = "Ты — редактор. Создаёшь КРАТКИЙ конспект. ТОЛЬКО LaTeX код. Сожми в 3-5 предложений."
    user_prompt = f"Сожми этот документ в КРАТКИЙ конспект (3-5 предложений). Сохрани только СУТЬ и ключевые формулы. НЕ переписывай весь код:\n\n{latex_code[:2000]}"
    result = _universal_chat(system_prompt, user_prompt, effective_model, task="collaboration")
    if result:
        result = _clean_markdown(result)
        return {"success": True, "result": result.strip(), "model": effective_model}
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

    if part_type == "theorem":
        system_prompt = "Ты — LaTeX эксперт. Создаёшь теорему с доказательством. Обязательно добавь: \\usepackage{amsthm} и \\newtheorem{theorem}{Теорема}."
        user_prompt = f"Сформулируй и докажи теорему: {description}\n\nОбязательно включи:\n1. \\usepackage{{amsthm}}\n2. \\newtheorem{{theorem}}{{Теорема}}\n3. \\begin{{theorem}}...\\end{{theorem}}\n4. \\begin{{proof}}...\\end{{proof}}\n\nНЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}."
    elif part_type == "proof":
        system_prompt = "Ты — LaTeX эксперт. Создаёшь доказательство. Обязательно добавь: \\usepackage{amsthm}."
        user_prompt = f"Докажи: {description}\n\nОбязательно включи:\n1. \\usepackage{{amsthm}}\n2. \\begin{{proof}}...\\end{{proof}}\n\nНЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}."
    elif part_type == "definition":
        system_prompt = "Ты — LaTeX эксперт. Создаёшь определение. Обязательно добавь: \\usepackage{amsthm} и \\newtheorem{definition}{Определение}."
        user_prompt = f"Дай определение: {description}\n\nОбязательно включи:\n1. \\usepackage{{amsthm}}\n2. \\newtheorem{{definition}}{{Определение}}\n3. \\begin{{definition}}...\\end{{definition}}\n\nНЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}."
    elif part_type == "example":
        system_prompt = "Ты — LaTeX эксперт. Создаёшь пример."
        user_prompt = f"Приведи пример: {description}\n\nТОЛЬКО LaTeX-код. НЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}."
    else:  # section
        system_prompt = f"Ты — LaTeX эксперт. Создаёшь {name}."
        user_prompt = f"Создай {name}: {description}\n\nТОЛЬКО \\section{{...}} и содержимое. НЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}."

    return _universal_stream_generator(system_prompt, user_prompt, model, task="part")


def explain_code_stream(code: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator(
        "Ты — LaTeX эксперт. Сначала общий смысл (1-2 предложения), затем разбор КАЖДОЙ команды. Используй Markdown.",
        f"Объясни этот LaTeX-код:\n\n{code}\n\n1. Общий смысл (1-2 предложения)\n2. Разбор КАЖДОЙ команды: что делает и зачем\nИспользуй **жирный** для названий команд.",
        model, task="explain"
    )


def explain_latex_stream(question: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — учитель LaTeX. Используй Markdown.",
                                       f"Вопрос: {question}\n\nОтвет с примером.", model, task="explain")


def math_solve_equation_stream(equation: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator(
        "Ты — математик. Используй ТОЛЬКО Markdown. Формулы ТОЛЬКО в $...$ для inline и $$...$$ для display. НИКОГДА не используй \\[ \\] или \\( \\).",
        f"Реши: {equation}\n\nПошагово. Ответ **жирным**. Формулы строго в $...$.",
        model, task="math"
    )


def math_derive_stream(expression: str, operation: str = "derive", model: str = DEFAULT_MODEL):
    if operation == "integrate":
        return _universal_stream_generator(
            "Ты — эксперт по матанализу. Формулы ТОЛЬКО в $...$ или $$...$$. НИКОГДА \\[ \\] или \\( \\).",
            f"Интеграл: ∫({expression})dx\n\nПошагово. Ответ **жирным** + C. Формулы в $...$.",
            model, task="math"
        )
    return _universal_stream_generator(
        "Ты — эксперт по матанализу. Формулы ТОЛЬКО в $...$ или $$...$$. НИКОГДА \\[ \\] или \\( \\).",
        f"Производная: d/dx({expression})\n\nПошагово. Ответ **жирным**. Формулы в $...$.",
        model, task="math"
    )


def math_physics_formula_stream(description: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator(
        "Ты — физик. Формулы ТОЛЬКО в $...$ или $$...$$. НИКОГДА \\[ \\] или \\( \\).",
        f"Задача: {description}\n\nФормула, шаги, ответ. Формулы в $...$.",
        model, task="math"
    )


def math_check_formula_stream(formula: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator(
        "Ты — математик. Формулы ТОЛЬКО в $...$ или $$...$$. НИКОГДА \\[ \\] или \\( \\).",
        f"Проверь: {formula}\n\nСинтаксис, семантика, вердикт. Формулы в $...$.",
        model, task="math"
    )


def generate_table_stream(csv_data: str, has_header: bool = True, use_booktabs: bool = True, model: str = DEFAULT_MODEL):
    h = "с заголовками" if has_header else "без заголовков"
    b = "с booktabs" if use_booktabs else "без booktabs"
    return _universal_stream_generator(
        "Ты — LaTeX эксперт. Создаёшь таблицы.",
        f"Таблица ({h}, {b}):\n\n{csv_data}\n\nОбязательно включи:\n1. \\usepackage{{booktabs}}\n2. \\begin{{tabular}} с \\toprule, \\midrule, \\bottomrule\n\nНЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}. Только код таблицы.",
        model, task="figures"
    )


def generate_diagram_stream(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL):
    return _universal_stream_generator(
        "Ты — TikZ эксперт. Создаёшь диаграммы.",
        f"Диаграмма: {prompt}\n\nОбязательно включи:\n1. \\usepackage{{tikz}}\n2. \\begin{{tikzpicture}}...\\end{{tikzpicture}}\n\nНЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}. Только код диаграммы.",
        model, task="figures"
    )


def generate_plot_stream(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "", model: str = DEFAULT_MODEL):
    t = f"Заголовок: {title}\n" if title else ""
    return _universal_stream_generator(
        "Ты — pgfplots эксперт. Создаёшь графики.",
        f"График: {expression}\nX: {xlabel}, Y: {ylabel}\n{t}\nОбязательно включи:\n1. \\usepackage{{tikz}}\n2. \\usepackage{{pgfplots}}\n3. \\pgfplotsset{{compat=1.18}}\n4. \\begin{{tikzpicture}} с \\begin{{axis}}...\\end{{axis}}\n\nНЕ добавляй \\documentclass, НЕ добавляй \\begin{{document}}.",
        model, task="figures"
    )


def fetch_bibtex_stream(identifier: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — библиограф.",
                                       f"BibTeX для: {identifier}\n\nЗаполни ВСЕ поля реальными данными. Только BibTeX.",
                                       model, task="references")


def format_references_stream(references: str, style: str = "ieee", model: str = DEFAULT_MODEL):
    names = {"ieee": "IEEE", "gost": "ГОСТ", "apa": "APA"}
    return _universal_stream_generator("Ты — библиограф.",
                                       f"Отформатируй по {names.get(style, style)}:\n\n{references}\n\nТолько текст, без пояснений и кодовых блоков.",
                                       model, task="references")


def check_citation_stream(citation: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — библиограф. Используй Markdown. НЕ выдумывай данные.",
                                       f"Проверь: {citation}\n\nФормат, полнота, исправление.", model,
                                       task="references")


def add_alt_text_stream(figure_code: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator(
        "Ты — эксперт по доступности. Создаёшь подробный alt-текст. Используй Markdown.",
        f"Создай alt-текст (3-4 предложения):\n\n{figure_code}\n\nОпиши **тип**, **оси**, **содержание**, **ключевую информацию**. Используй **жирный** для важных деталей.",
        model, task="accessibility"
    )


def check_colors_stream(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — колориметрист.",
                                       f"Проверь: {', '.join(colors)}\n\nКонтрастность, дальтонизм, рекомендации.",
                                       model, task="accessibility")


def check_template_stream(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL):
    names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    return _universal_stream_generator("Ты — LaTeX эксперт. НЕ добавляй лишних команд.",
                                       f"Проверь на {names.get(template, template)}:\n\n{latex_code}\n\nВердикт, проблемы (кратко).",
                                       model, task="accessibility")


def get_diff_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — эксперт по сравнению. Используй Markdown.",
                                       f"Сравни:\nСтарая: {old_text}\nНовая: {new_text}\n\n- удалено\n+ добавлено",
                                       model, task="collaboration")


def summarize_changes_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    return _universal_stream_generator("Ты — ассистент. Используй Markdown.",
                                       f"Опиши:\nСтарая: {old_text}\nНовая: {new_text}\n\n**Добавлено**, *удалено*.",
                                       model, task="collaboration")


def summarize_document_stream(latex_code: str, model: str = DEFAULT_MODEL):
    effective_model = model
    if model == DEFAULT_MODEL:
        effective_model = OPENROUTER_FREE_MODELS[0]
    return _universal_stream_generator("Ты — редактор.", f"Сожми в 3-5 предложений:\n\n{latex_code[:2000]}\n\nТолько суть и ключевые формулы. LaTeX код.", effective_model, task="collaboration")