import requests
import os
import time
import json
import re
from typing import Optional, Dict, Any, Generator

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma4-e4b")


def get_available_models() -> list:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            return [m["name"] for m in response.json().get("models", [])]
    except:
        pass
    return []


def ensure_model(model: str) -> bool:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code != 200:
            print(f"Ollama not available at {OLLAMA_URL}")
            return False
    except Exception as e:
        print(f"Ollama connection error: {e}")
        return False

    models = get_available_models()
    if model in models:
        print(f"Model {model} already available")
        return True

    print(f"Downloading model {model}... (this may take 5-15 minutes)")
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": model},
            timeout=1800
        )
        if response.status_code == 200:
            print(f"Model {model} downloaded successfully")
            return True
        else:
            print(f"Failed to download model: {response.status_code}")
            return False
    except Exception as e:
        print(f"Download error: {e}")
        return False


def get_model_config(model: str, task: str = "default") -> dict:
    model_lower = model.lower()

    base = {
        "temperature": 0.1,
        "top_p": 0.95,
        "top_k": 40,
        "repeat_penalty": 1.1,
    }

    if "gemma" in model_lower:
        base["temperature"] = 0.15
        base["top_p"] = 0.93

    if task == "document":
        base["num_predict"] = 4096
        base["num_ctx"] = 8192
    elif task == "formula":
        base["num_predict"] = 512
        base["num_ctx"] = 2048
    elif task == "part":
        base["num_predict"] = 2048
        base["num_ctx"] = 4096
    elif task == "explain_code":
        base["num_predict"] = 2048
        base["num_ctx"] = 4096
        base["temperature"] = 0.3
    elif task == "explain_latex":
        base["num_predict"] = 2048
        base["num_ctx"] = 4096
        base["temperature"] = 0.3
    else:
        base["num_predict"] = 4096
        base["num_ctx"] = 8192

    return base


# ============================================
# ВНУТРЕННИЕ ФУНКЦИИ ОТПРАВКИ ЗАПРОСОВ
# ============================================

def _call_ollama(messages: list, model: str = DEFAULT_MODEL, config: dict = None):
    if not ensure_model(model):
        return None

    if config is None:
        config = get_model_config(model)

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            **config,
            "stop": ["```", "```latex", "```tex", "###", "Explanation:", "Here is your LaTeX:"]
        }
    }

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=300,
            stream=True
        )
        return response
    except Exception as e:
        print(f"Ollama request error: {e}")
        return None


def _read_stream(response) -> str:
    if not response:
        return ""

    full_text = ""
    try:
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if "message" in data and "content" in data["message"]:
                        full_text += data["message"]["content"]
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Stream read error: {e}")

    return full_text.strip()


def _stream_generator(messages: list, model: str = DEFAULT_MODEL, task: str = "default") -> Generator[str, None, None]:
    config = get_model_config(model, task)
    response = _call_ollama(messages, model, config)
    if not response:
        yield f"data: {json.dumps({'error': 'No response from Ollama'})}\n\n"
        return

    try:
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if "message" in data and "content" in data["message"]:
                        content = data["message"]["content"]
                        content = re.sub(r'```latex\s*', '', content)
                        content = re.sub(r'```\s*', '', content)
                        yield f"data: {json.dumps({'token': content})}\n\n"
                    if data.get("done", False):
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


# ============================================
# ФУНКЦИИ ГЕНЕРАЦИИ
# ============================================

def generate_document(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": "Ты — генератор LaTeX-документов. Создаёшь ТОЛЬКО готовый к компиляции код без комментариев."
        },
        {
            "role": "user",
            "content": f"Создай полный LaTeX документ на русском языке.\n\nТема: {description}\n\nТребования:\n- Начинай строго с \\documentclass{{article}}\n- Подключи пакеты: amsmath, amssymb\n- Используй кириллицу\n- Не добавляй Markdown\n- Не используй ``` блоки\n- Только код, без пояснений"
        }
    ]
    config = get_model_config(model, "document")
    response = _call_ollama(messages, model, config)
    if response:
        code = _read_stream(response)
        code = re.sub(r'```latex\s*', '', code)
        code = re.sub(r'```\s*', '', code)
        return {"success": True, "code": code, "model": model}
    return {"success": False, "error": "No response from Ollama"}


def generate_document_stream(description: str, model: str = DEFAULT_MODEL):
    messages = [
        {
            "role": "system",
            "content": "Ты — генератор LaTeX-документов. Создаёшь ТОЛЬКО готовый к компиляции код без комментариев."
        },
        {
            "role": "user",
            "content": f"Создай полный LaTeX документ на русском языке.\n\nТема: {description}\n\nТребования:\n- Начинай строго с \\documentclass{{article}}\n- Подключи пакеты: amsmath, amssymb\n- Используй кириллицу\n- Не добавляй Markdown\n- Не используй ``` блоки\n- Только код, без пояснений"
        }
    ]
    return _stream_generator(messages, model, "document")


def generate_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": "Ты — математический ассистент. Создаёшь ТОЛЬКО одну формулу в LaTeX без документа."
        },
        {
            "role": "user",
            "content": f"Создай только математическую формулу. НЕ НУЖНО создавать документ.\n\nЗапрос: {description}\n\nТребования:\n- Только формула, без \\documentclass и окружений\n- Используй \\[ ... \\] или \\( ... \\) для отображения\n- Никаких пояснений или комментариев"
        }
    ]
    config = get_model_config(model, "formula")
    response = _call_ollama(messages, model, config)
    if response:
        formula = _read_stream(response)
        formula = re.sub(r'```latex\s*', '', formula)
        formula = re.sub(r'```\s*', '', formula)
        return {"success": True, "code": formula, "model": model}
    return {"success": False, "error": "No response from Ollama"}


def generate_formula_stream(description: str, model: str = DEFAULT_MODEL):
    messages = [
        {
            "role": "system",
            "content": "Ты — математический ассистент. Создаёшь ТОЛЬКО одну формулу в LaTeX без документа."
        },
        {
            "role": "user",
            "content": f"Создай только математическую формулу. НЕ НУЖНО создавать документ.\n\nЗапрос: {description}\n\nТребования:\n- Только формула, без \\documentclass и окружений\n- Используй \\[ ... \\] или \\( ... \\) для отображения\n- Никаких пояснений или комментариев"
        }
    ]
    return _stream_generator(messages, model, "formula")


def generate_part(description: str, part_type: str = "section", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    part_descriptions = {
        "section": "секцию (раздел) с заголовком",
        "theorem": "теорему с доказательством",
        "proof": "доказательство",
        "definition": "определение",
        "example": "пример"
    }
    part_text = part_descriptions.get(part_type, part_type)

    messages = [
        {
            "role": "system",
            "content": f"Ты — эксперт по LaTeX. Создаёшь {part_text} без \\documentclass."
        },
        {
            "role": "user",
            "content": f"Создай LaTeX-код для {part_text} на тему: {description}\n\nТребования:\n- Не добавляй \\documentclass и \\begin{{document}}\n- Только содержимое\n- Используй кириллицу\n- Только код, без пояснений"
        }
    ]
    config = get_model_config(model, "part")
    response = _call_ollama(messages, model, config)
    if response:
        code = _read_stream(response)
        code = re.sub(r'```latex\s*', '', code)
        code = re.sub(r'```\s*', '', code)
        return {"success": True, "code": code, "model": model}
    return {"success": False, "error": "No response from Ollama"}


def generate_part_stream(description: str, part_type: str = "section", model: str = DEFAULT_MODEL):
    part_descriptions = {
        "section": "секцию (раздел) с заголовком",
        "theorem": "теорему с доказательством",
        "proof": "доказательство",
        "definition": "определение",
        "example": "пример"
    }
    part_text = part_descriptions.get(part_type, part_type)

    messages = [
        {
            "role": "system",
            "content": f"Ты — эксперт по LaTeX. Создаёшь {part_text} без \\documentclass."
        },
        {
            "role": "user",
            "content": f"Создай {part_text} на тему: {description}"
        }
    ]
    return _stream_generator(messages, model, "part")


# ============================================
# ФУНКЦИИ ОБЪЯСНЕНИЯ
# ============================================

def explain_code(code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по LaTeX. Объясняешь код кратко и простым языком. НЕ используй Markdown."
        },
        {
            "role": "user",
            "content": f"""Объясни этот LaTeX-код простыми словами. Для каждой команды напиши, что она делает.

Код:
{code}"""
        }
    ]
    config = get_model_config(model, "explain_code")
    response = _call_ollama(messages, model, config)
    if response:
        explanation = _read_stream(response)
        return {"success": True, "explanation": explanation, "model": model}
    return {"success": False, "error": "No response from Ollama"}


def explain_code_stream(code: str, model: str = DEFAULT_MODEL):
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по LaTeX. Объясняешь код кратко и простым языком. НЕ используй Markdown."
        },
        {
            "role": "user",
            "content": f"""Объясни этот LaTeX-код простыми словами. Для каждой команды напиши, что она делает.

Код:
{code}"""
        }
    ]
    return _stream_generator(messages, model, "explain_code")


def explain_latex(question: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": "Ты — учитель LaTeX. Ты отвечаешь на вопросы кратко и показываешь примеры кода. НЕ используй Markdown."
        },
        {
            "role": "user",
            "content": f"""Вопрос по LaTeX: {question}

В ответе:
1. Дай краткое объяснение (1-2 предложения)
2. Покажи ПРИМЕР LaTeX-кода"""
        }
    ]
    config = get_model_config(model, "explain_latex")
    response = _call_ollama(messages, model, config)
    if response:
        explanation = _read_stream(response)
        return {"success": True, "explanation": explanation, "model": model}
    return {"success": False, "error": "No response from Ollama"}


def explain_latex_stream(question: str, model: str = DEFAULT_MODEL):
    messages = [
        {
            "role": "system",
            "content": "Ты — учитель LaTeX. Ты отвечаешь на вопросы кратко и показываешь примеры кода. НЕ используй Markdown."
        },
        {
            "role": "user",
            "content": f"""Вопрос по LaTeX: {question}

В ответе:
1. Дай краткое объяснение (1-2 предложения)
2. Покажи ПРИМЕР LaTeX-кода"""
        }
    ]
    return _stream_generator(messages, model, "explain_latex")

# ============================================
# MATH ФУНКЦИИ
# ============================================

def math_solve_equation(equation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Решение уравнения"""
    messages = [
        {
            "role": "system",
            "content": "Ты — математический ассистент. Решаешь уравнения пошагово. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Реши уравнение:\n{equation}\n\nПокажи пошаговое решение. Каждый шаг на новой строке. Ответ выдели."
        }
    ]
    config = get_model_config(model, "document")
    response = _call_ollama(messages, model, config)
    if response:
        result = _read_stream(response)
        return {"success": True, "result": result, "model": model}
    return {"success": False, "error": "No response from Ollama"}

def math_solve_equation_stream(equation: str, model: str = DEFAULT_MODEL):
    """Решение уравнения (stream)"""
    messages = [
        {
            "role": "system",
            "content": "Ты — математический ассистент. Решаешь уравнения пошагово. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Реши уравнение:\n{equation}\n\nПокажи пошаговое решение. Каждый шаг на новой строке. Ответ выдели."
        }
    ]
    return _stream_generator(messages, model, "document")


def math_derive(expression: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Нахождение производной/интеграла"""
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по математическому анализу. Находишь производные и интегралы. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Найди производную (или интеграл) для выражения:\n{expression}\n\nПокажи пошаговое решение. Каждый шаг на новой строке. Ответ выдели."
        }
    ]
    config = get_model_config(model, "document")
    response = _call_ollama(messages, model, config)
    if response:
        result = _read_stream(response)
        return {"success": True, "result": result, "model": model}
    return {"success": False, "error": "No response from Ollama"}

def math_derive_stream(expression: str, model: str = DEFAULT_MODEL):
    """Нахождение производной/интеграла (stream)"""
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по математическому анализу. Находишь производные и интегралы. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Найди производную (или интеграл) для выражения:\n{expression}\n\nПокажи пошаговое решение. Каждый шаг на новой строке. Ответ выдели."
        }
    ]
    return _stream_generator(messages, model, "document")


def math_physics_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Генерация физической формулы, выражение переменной"""
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по физике и математике. Выводишь физические формулы и выражаешь переменные. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Задача по физике:\n{description}\n\n1. Запиши физическую формулу\n2. Вырази указанную переменную\n3. Покажи пошаговое преобразование\n4. Выдели ответ"
        }
    ]
    config = get_model_config(model, "document")
    response = _call_ollama(messages, model, config)
    if response:
        result = _read_stream(response)
        return {"success": True, "result": result, "model": model}
    return {"success": False, "error": "No response from Ollama"}

def math_physics_formula_stream(description: str, model: str = DEFAULT_MODEL):
    """Генерация физической формулы (stream)"""
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по физике и математике. Выводишь физические формулы и выражаешь переменные. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Задача по физике:\n{description}\n\n1. Запиши физическую формулу\n2. Вырази указанную переменную\n3. Покажи пошаговое преобразование\n4. Выдели ответ"
        }
    ]
    return _stream_generator(messages, model, "document")


def math_check_formula(formula: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Проверка формулы на семантические и синтаксические ошибки"""
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по математике. Проверяешь формулы на ошибки. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Проверь эту формулу на синтаксические и семантические ошибки:\n\n{formula}\n\nОтветь:\n1. Синтаксис: правильно/неправильно (если ошибки — перечисли)\n2. Семантика: правильно/неправильно (если ошибки — объясни)\n3. Если есть ошибки — исправь формулу\n4. Если формула правильная — подтверди это"
        }
    ]
    config = get_model_config(model, "document")
    response = _call_ollama(messages, model, config)
    if response:
        result = _read_stream(response)
        return {"success": True, "result": result, "model": model}
    return {"success": False, "error": "No response from Ollama"}

def math_check_formula_stream(formula: str, model: str = DEFAULT_MODEL):
    """Проверка формулы (stream)"""
    messages = [
        {
            "role": "system",
            "content": "Ты — эксперт по математике. Проверяешь формулы на ошибки. НЕ используй Markdown. Выводи формулы в LaTeX."
        },
        {
            "role": "user",
            "content": f"Проверь эту формулу на синтаксические и семантические ошибки:\n\n{formula}\n\nОтветь:\n1. Синтаксис: правильно/неправильно (если ошибки — перечисли)\n2. Семантика: правильно/неправильно (если ошибки — объясни)\n3. Если есть ошибки — исправь формулу\n4. Если формула правильная — подтверди это"
        }
    ]
    return _stream_generator(messages, model, "document")

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def fix_latex_errors(code: str, errors: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": "Ты — эксперт по LaTeX. Исправляешь ошибки."},
        {"role": "user",
         "content": f"Исправь ошибки в LaTeX коде. Верни только исправленный код.\n\nОшибки: {errors}\n\nКод: {code}"}
    ]
    response = _call_ollama(messages, model)
    if response:
        fixed = _read_stream(response)
        fixed = fixed.replace("```latex", "").replace("```", "").strip()
        return {"success": True, "code": fixed, "model": model}
    return {"success": False, "error": "No response from Ollama"}