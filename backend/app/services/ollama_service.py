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

def get_model_config(model: str) -> dict:
    base = {
        "temperature": 0.1,
        "top_p": 0.95,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "num_predict": 4096,
        "num_ctx": 8192,
        "num_threads": os.cpu_count(),
    }

    if "gemma" in model.lower():
        base["temperature"] = 0.15
        base["top_p"] = 0.93
    elif "qwen" in model.lower():
        base["temperature"] = 0.2
        base["num_ctx"] = 4096
        base["num_predict"] = 2048
    elif "deepseek" in model.lower():
        base["temperature"] = 0.05
        base["top_p"] = 0.97

    return base

def generate_stream(prompt: str, model: str = DEFAULT_MODEL) -> Generator[str, None, None]:
    """Потоковая генерация через /api/chat с system role"""
    if not ensure_model(model):
        yield f"data: {json.dumps({'error': f'Model {model} not available'})}\n\n"
        return

    config = get_model_config(model)

    # Формируем запрос в формате /api/chat
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": """Ты — эксперт по LaTeX. Твоя задача — генерировать ТОЛЬКО валидный LaTeX код.

Правила:
- НЕ используй Markdown (**, ##, -)
- НЕ используй ``` блоки
- НЕ добавляй пояснения
- НЕ добавляй комментарии
- Все окружения должны быть закрыты
- Код должен компилироваться без ошибок

Вывод: только LaTeX код."""
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
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

        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if "message" in data and "content" in data["message"]:
                        content = data["message"]["content"]
                        # Очищаем от маркдауна в реальном времени
                        content = re.sub(r'```latex\s*', '', content)
                        content = re.sub(r'```\s*', '', content)
                        content = re.sub(r'Here is your LaTeX:\s*', '', content, flags=re.IGNORECASE)
                        yield f"data: {json.dumps({'token': content})}\n\n"
                    if data.get("done", False):
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

def generate(prompt: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Обычная генерация через /api/chat (без потока)"""
    if not ensure_model(model):
        return {"success": False, "error": f"Model {model} not available"}

    config = get_model_config(model)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": """Ты — эксперт по LaTeX. Твоя задача — генерировать ТОЛЬКО валидный LaTeX код.

Правила:
- НЕ используй Markdown (**, ##, -)
- НЕ используй ``` блоки
- НЕ добавляй пояснения
- НЕ добавляй комментарии
- Все окружения должны быть закрыты
- Код должен компилироваться без ошибок

Вывод: только LaTeX код."""
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": False,
        "options": {
            **config,
            "stop": ["```", "```latex", "```tex", "###", "Explanation:", "Here is your LaTeX:"]
        }
    }

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=120
        )

        if response.status_code == 200:
            text = response.json()["message"]["content"].strip()

            # Очистка
            text = re.sub(r'```latex\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = re.sub(r'Here is your LaTeX:\s*', '', text, flags=re.IGNORECASE)
            text = re.sub(r'^Here is the LaTeX code:\s*', '', text, flags=re.IGNORECASE)
            text = re.sub(r'(\*{1,2})([^*]+)\1', r'\2', text)  # **bold** → bold
            text = re.sub(r'#{1,6}\s+', '', text)  # заголовки

            return {"success": True, "text": text.strip(), "model": model}

        return {"success": False, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        return {"success": False, "error": str(e)}

def generate_latex(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    prompt = f"Сгенерируй LaTeX код для: {description}"
    result = generate(prompt, model)
    if result["success"]:
        return {"success": True, "code": result["text"], "model": result["model"]}
    return result

def explain_latex(code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    prompt = f"Объясни этот LaTeX код:\n{code}"
    return generate(prompt, model)

def fix_latex_errors(code: str, errors: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    prompt = f"Исправь ошибки в LaTeX коде. Верни только исправленный код.\nОшибки: {errors}\nКод: {code}"
    result = generate(prompt, model)
    if result["success"]:
        fixed = result["text"]
        fixed = fixed.replace("```latex", "").replace("```", "").strip()
        return {"success": True, "code": fixed}
    return result

# ============================================
# Дополнительные AI функции
# ============================================

def derive_equation(expression: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Вычисление производной или упрощение выражения"""
    prompt = f"""Вычисли производную или упрости математическое выражение.
Верни ответ в формате:
Шаги:
1. ...
2. ...
Финальный результат: ...

Выражение: {expression}"""
    
    result = generate(prompt, model)
    if result["success"]:
        text = result["text"]
        steps = []
        final_result = ""
        for line in text.split('\n'):
            if line.strip().startswith('Финальный результат:') or line.strip().startswith('Final result:'):
                final_result = line.split(':', 1)[1].strip()
            elif line.strip() and not line.strip().startswith('Шаги:') and not line.strip().startswith('Steps:'):
                steps.append(line.strip())
        return {"success": True, "steps": steps, "final_result": final_result, "model": result["model"]}
    return result

def check_units(expression: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Проверка размерностей физических величин"""
    prompt = f"""Проверь размерность (единицы измерения) в физическом выражении.
Ответь:
Consistent: Yes/No
Details: пояснение

Выражение: {expression}"""
    
    result = generate(prompt, model)
    if result["success"]:
        text = result["text"]
        consistent = "yes" in text.lower() and "no" not in text.lower()
        details = text
        return {"success": True, "consistent": consistent, "details": details, "model": result["model"]}
    return result

def verify_equation(lhs: str, rhs: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Проверка равенства двух выражений"""
    prompt = f"""Проверь, равны ли эти два математических выражения.
Лев часть: {lhs}
Прав часть: {rhs}
Ответь:
Equivalent: Yes/No
Simplified LHS: ...
Simplified RHS: ..."""
    
    result = generate(prompt, model)
    if result["success"]:
        text = result["text"]
        equivalent = "yes" in text.lower() and "no" not in text.lower()
        simplified_lhs = ""
        simplified_rhs = ""
        for line in text.split('\n'):
            if 'Simplified LHS:' in line:
                simplified_lhs = line.split(':', 1)[1].strip()
            if 'Simplified RHS:' in line:
                simplified_rhs = line.split(':', 1)[1].strip()
        return {"success": True, "equivalent": equivalent, "simplified_lhs": simplified_lhs, "simplified_rhs": simplified_rhs, "model": result["model"]}
    return result

def generate_table(csv_data: str, has_header: bool = True, use_booktabs: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Генерация LaTeX таблицы из CSV данных"""
    prompt = f"""Сгенерируй LaTeX код для таблицы из следующих данных:
{csv_data}
Заголовки: {'да' if has_header else 'нет'}
Использовать booktabs: {'да' if use_booktabs else 'нет'}
Верни ТОЛЬКО код таблицы, без пояснений."""
    
    result = generate(prompt, model)
    if result["success"]:
        code = result["text"]
        code = code.replace("```latex", "").replace("```", "").strip()
        return {"success": True, "latex": code, "model": result["model"]}
    return result

def generate_diagram(prompt_desc: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Генерация LaTeX диаграммы (TikZ)"""
    prompt = f"""Сгенерируй LaTeX код для диаграммы используя TikZ.
Описание: {prompt_desc}
Верни ТОЛЬКО код, без пояснений.
Начинай с \\begin{{tikzpicture}} и заканчивай \\end{{tikzpicture}}."""
    
    result = generate(prompt, model)
    if result["success"]:
        code = result["text"]
        code = code.replace("```latex", "").replace("```", "").strip()
        return {"success": True, "latex": code, "model": result["model"]}
    return result

def fetch_bibtex(identifier: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Получение BibTeX по DOI или arXiv ID (через AI)"""
    prompt = f"""Сгенерируй BibTeX запись для публикации с идентификатором: {identifier}
Верни ТОЛЬКО BibTeX код, без пояснений.
Начинай с @article{{...}} или @inproceedings{{...}}."""
    
    result = generate(prompt, model)
    if result["success"]:
        bibtex = result["text"]
        bibtex = bibtex.replace("```bibtex", "").replace("```", "").strip()
        return {"success": True, "bibtex": bibtex, "model": result["model"]}
    return result

def add_alt_text(figure_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Генерация alt текста для фигуры"""
    prompt = f"""Сгенерируй alt текст (описание для скринридера) для LaTeX фигуры:
{figure_code}
Ответь ТОЛЬКО текстом, без LaTeX кода."""
    
    result = generate(prompt, model)
    if result["success"]:
        return {"success": True, "alt_text": result["text"], "model": result["model"]}
    return result

def check_colors(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Проверка цветов на соответствие стандартам доступности"""
    prompt = f"""Проверь цвета на соответствие стандартам доступности для людей с дальтонизмом.
Цвета: {', '.join(colors)}
Тип палитры: {palette_type}
Ответь:
Compliant: Yes/No
Issues: список проблем (если есть)"""
    
    result = generate(prompt, model)
    if result["success"]:
        text = result["text"]
        compliant = "yes" in text.lower() and "no" not in text.lower()
        issues = []
        for line in text.split('\n'):
            if 'Issues:' in line:
                issues_text = line.split(':', 1)[1].strip()
                if issues_text and issues_text != 'None' and issues_text != 'none':
                    issues = [issues_text]
        return {"success": True, "compliant": compliant, "issues": issues, "model": result["model"]}
    return result

def check_template(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Проверка соответствия шаблону (IEEE, ACM)"""
    prompt = f"""Проверь LaTeX код на соответствие шаблону {template.upper()}.
Ответь:
Compliant: Yes/No
Issues: список проблем (если есть)"""
    
    result = generate(prompt, model)
    if result["success"]:
        text = result["text"]
        compliant = "yes" in text.lower() and "no" not in text.lower()
        issues = []
        for line in text.split('\n'):
            if 'Issues:' in line:
                issues_text = line.split(':', 1)[1].strip()
                if issues_text and issues_text != 'None' and issues_text != 'none':
                    issues = [issues_text]
        return {"success": True, "compliant": compliant, "issues": issues, "model": result["model"]}
    return result

def get_diff(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Генерация diff между двумя версиями текста"""
    prompt = f"""Покажи различия между этими двумя текстами в формате unified diff:
Оригинал:
{old_text}
Новая версия:
{new_text}
Верни ТОЛЬКО diff."""
    
    result = generate(prompt, model)
    if result["success"]:
        return {"success": True, "diff": result["text"], "model": result["model"]}
    return result

def summarize_changes(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Суммирование изменений между версиями"""
    prompt = f"""Кратко опиши основные изменения между этими текстами:
Оригинал:
{old_text}
Новая версия:
{new_text}
Ответь в виде короткого списка или абзаца."""
    
    return generate(prompt, model)