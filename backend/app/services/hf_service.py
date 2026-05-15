import requests
import os
import json
import re
from typing import Optional, Dict, Any, Generator

# HuggingFace Inference API
HF_API_URL = "https://api-inference.huggingface.co/models"
HF_TOKEN = os.getenv("HF_TOKEN", "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")

# Модель по умолчанию
DEFAULT_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# Фоллбек-модели (если основная недоступна)
FALLBACK_MODELS = [
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "meta-llama/Meta-Llama-3-8B-Instruct",
    "google/gemma-1.1-7b-it",
]

# Токены для ротации
TOKENS = [HF_TOKEN]


def get_available_models() -> list:
    return [DEFAULT_MODEL] + FALLBACK_MODELS


def _hf_request(messages: list, model: str = DEFAULT_MODEL) -> str:
    """Отправляет запрос к HuggingFace Inference API с ротацией токенов"""

    for token in TOKENS:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # Правильный URL для Inference API
        url = f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": messages}
            ],
            "max_tokens": 4096,
            "temperature": 0.2,
            "top_p": 0.95,
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=120
            )

            print(f"Status: {response.status_code}, URL: {url}")

            if response.status_code == 200:
                result = response.json()
                # Формат ответа: {"choices": [{"message": {"content": "..."}}]}
                if "choices" in result and len(result["choices"]) > 0:
                    return result["choices"][0]["message"]["content"]
                return ""

            elif response.status_code == 429:
                print(f"Rate limited, switching token...")
                continue
            elif response.status_code == 503:
                print(f"Model loading, waiting...")
                import time
                time.sleep(10)
                continue
            else:
                print(f"Response: {response.text[:300]}")
                continue

        except Exception as e:
            print(f"Request error: {e}")
            continue

    return ""


def _hf_chat_request(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Отправляет запрос в формате чата"""
    messages = f"<s>[INST] {system_prompt}\n\n{user_prompt} [/INST]"
    return _hf_request(messages, model)


def _text_to_stream(text: str, chunk_size: int = 10) -> Generator[str, None, None]:
    """Разбивает текст на куски для имитации стриминга"""
    words = text.split(' ')
    buffer = ""

    for i, word in enumerate(words):
        buffer += word + " "

        if (i + 1) % chunk_size == 0 or word.endswith('.') or word.endswith('\n'):
            yield f"data: {json.dumps({'token': buffer})}\n\n"
            buffer = ""

    if buffer.strip():
        yield f"data: {json.dumps({'token': buffer})}\n\n"

    yield f"data: {json.dumps({'done': True})}\n\n"


# ============================================
# ФУНКЦИИ ГЕНЕРАЦИИ
# ============================================

def generate_document(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — генератор LaTeX-документов. Создаёшь ТОЛЬКО готовый к компиляции код без комментариев."
    user_prompt = f"Создай полный LaTeX документ на русском языке.\n\nТема: {description}\n\nТребования:\n- Начинай строго с \\documentclass{{article}}\n- Подключи пакеты: amsmath, amssymb\n- Используй кириллицу\n- Только код, без пояснений"

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def generate_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математический ассистент. Создаёшь ТОЛЬКО одну формулу в LaTeX."
    user_prompt = f"Создай только математическую формулу для: {description}\n\nТолько формула, без \\documentclass."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def generate_part(description: str, part_type: str = "section", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    part_names = {
        "section": "секцию (раздел)",
        "theorem": "теорему с доказательством",
        "proof": "доказательство",
        "definition": "определение",
        "example": "пример"
    }
    part_name = part_names.get(part_type, part_type)

    system_prompt = f"Ты — эксперт по LaTeX. Создаёшь {part_name} без \\documentclass."
    user_prompt = f"Создай {part_name} на тему: {description}\n\nТолько LaTeX-код, без \\documentclass."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


# ============================================
# ФУНКЦИИ ОБЪЯСНЕНИЯ
# ============================================

def explain_code(code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по LaTeX. Объясняешь код простым языком."
    user_prompt = f"Объясни этот LaTeX-код:\n\n{code}"

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def explain_latex(question: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — учитель LaTeX. Отвечаешь на вопросы кратко и показываешь примеры кода."
    user_prompt = f"Вопрос по LaTeX: {question}\n\nДай краткий ответ и покажи пример кода."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "explanation": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


# ============================================
# MATH ФУНКЦИИ
# ============================================

def math_solve_equation(equation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — математический ассистент. Решаешь уравнения пошагово."
    user_prompt = f"Реши уравнение: {equation}\n\nПокажи пошаговое решение. Ответ выдели."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def math_derive(expression: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по математическому анализу. Находишь производные."
    user_prompt = f"Найди производную для: {expression}\n\nПокажи пошаговое решение. Ответ выдели."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def math_physics_formula(description: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по физике. Выводишь физические формулы."
    user_prompt = f"Задача: {description}\n\nЗапиши формулу, вырази переменную, покажи шаги, выдели ответ."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def math_check_formula(formula: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по математике. Проверяешь формулы на ошибки."
    user_prompt = f"Проверь формулу: {formula}\n\nСинтаксис, семантика, исправь если нужно."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


# ============================================
# FIGURES ФУНКЦИИ
# ============================================

def generate_table(csv_data: str, has_header: bool = True, use_booktabs: bool = True, model: str = DEFAULT_MODEL) -> \
Dict[str, Any]:
    header_text = "с заголовками" if has_header else "без заголовков"
    booktabs_text = "с booktabs" if use_booktabs else "без booktabs"

    system_prompt = "Ты — эксперт по LaTeX. Создаёшь таблицы."
    user_prompt = f"Создай LaTeX таблицу из этих данных ({header_text}, {booktabs_text}):\n\n{csv_data}\n\nТолько код таблицы, без \\documentclass."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def generate_diagram(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по TikZ. Создаёшь диаграммы."
    user_prompt = f"Создай TikZ диаграмму:\n{prompt}\n\nИспользуй \\begin{{tikzpicture}}...\\end{{tikzpicture}}, без \\documentclass."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def generate_plot(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "", model: str = DEFAULT_MODEL) -> \
Dict[str, Any]:
    title_text = f"Заголовок: {title}\n" if title else ""

    system_prompt = "Ты — эксперт по pgfplots. Создаёшь графики."
    user_prompt = f"Создай график через pgfplots:\n\nФункция: {expression}\nОсь X: {xlabel}\nОсь Y: {ylabel}\n{title_text}\nТолько код, без \\documentclass."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


# ============================================
# REFERENCES ФУНКЦИИ
# ============================================

def fetch_bibtex(identifier: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — библиографический ассистент. Генерируешь BibTeX записи."
    user_prompt = f"Создай BibTeX запись для: {identifier}\n\nТолько BibTeX код."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```bibtex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def format_references(references: str, style: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    style_names = {"ieee": "IEEE", "gost": "ГОСТ", "apa": "APA"}
    style_name = style_names.get(style, style)

    system_prompt = f"Ты — эксперт по библиографии. Форматируешь ссылки по стандарту {style_name}."
    user_prompt = f"Отформатируй список литературы по {style_name}:\n\n{references}"

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def check_citation(citation: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по библиографии. Проверяешь оформление ссылок."
    user_prompt = f"Проверь правильность оформления:\n\n{citation}\n\nОцени формат, полноту, исправь ошибки."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


# ============================================
# ACCESSIBILITY ФУНКЦИИ
# ============================================

def add_alt_text(figure_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по доступности. Создаёшь alt-описания."
    user_prompt = f"Создай alt-текст для:\n\n{figure_code}\n\nОдно-два предложения, опиши суть."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def check_colors(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    color_list = ', '.join(colors)

    system_prompt = "Ты — эксперт по колориметрии. Проверяешь цвета на дальтонизм."
    user_prompt = f"Проверь цвета на различимость: {color_list}\n\nСтатус, проблемы, рекомендации."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def check_template(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    template_names = {"ieee": "IEEE", "acm": "ACM", "gost": "ГОСТ"}
    template_name = template_names.get(template, template)

    system_prompt = f"Ты — эксперт по LaTeX. Проверяешь соответствие шаблону {template_name}."
    user_prompt = f"Проверь код на соответствие {template_name}:\n\n{latex_code}\n\nСоответствие, проблемы, рекомендации."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


# ============================================
# COLLABORATION ФУНКЦИИ
# ============================================

def get_diff(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по сравнению текстов. Создаёшь unified diff."
    user_prompt = f"Сравни версии:\n\nСтарая:\n{old_text}\n\nНовая:\n{new_text}\n\n+ добавлено, - удалено."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def summarize_changes(old_text: str, new_text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — ассистент. Кратко описываешь изменения."
    user_prompt = f"Опиши изменения кратко:\n\nСтарая:\n{old_text}\n\nНовая:\n{new_text}"

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def summarize_document(latex_code: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — научный редактор. Создаёшь сжатые конспекты."
    user_prompt = f"Сделай краткий конспект LaTeX-документа:\n\n{latex_code}\n\nСохрани структуру и формулы."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "result": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


def fix_latex_errors(code: str, errors: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    system_prompt = "Ты — эксперт по LaTeX. Исправляешь ошибки."
    user_prompt = f"Исправь ошибки:\n\nОшибки: {errors}\n\nКод:\n{code}\n\nВерни только исправленный код."

    result = _hf_chat_request(system_prompt, user_prompt, model)
    if result:
        result = re.sub(r'```latex\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return {"success": True, "code": result.strip(), "model": model}
    return {"success": False, "error": "No response from HuggingFace API"}


# ============================================
# STREAM ФУНКЦИИ
# ============================================

def generate_document_stream(description: str, model: str = DEFAULT_MODEL):
    result = generate_document(description, model)
    if result["success"]:
        return _text_to_stream(result["code"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def generate_formula_stream(description: str, model: str = DEFAULT_MODEL):
    result = generate_formula(description, model)
    if result["success"]:
        return _text_to_stream(result["code"], chunk_size=3)
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def generate_part_stream(description: str, part_type: str = "section", model: str = DEFAULT_MODEL):
    result = generate_part(description, part_type, model)
    if result["success"]:
        return _text_to_stream(result["code"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def explain_code_stream(code: str, model: str = DEFAULT_MODEL):
    result = explain_code(code, model)
    if result["success"]:
        return _text_to_stream(result["explanation"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def explain_latex_stream(question: str, model: str = DEFAULT_MODEL):
    result = explain_latex(question, model)
    if result["success"]:
        return _text_to_stream(result["explanation"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def math_solve_equation_stream(equation: str, model: str = DEFAULT_MODEL):
    result = math_solve_equation(equation, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def math_derive_stream(expression: str, model: str = DEFAULT_MODEL):
    result = math_derive(expression, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def math_physics_formula_stream(description: str, model: str = DEFAULT_MODEL):
    result = math_physics_formula(description, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def math_check_formula_stream(formula: str, model: str = DEFAULT_MODEL):
    result = math_check_formula(formula, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def generate_table_stream(csv_data: str, has_header: bool = True, use_booktabs: bool = True,
                          model: str = DEFAULT_MODEL):
    result = generate_table(csv_data, has_header, use_booktabs, model)
    if result["success"]:
        return _text_to_stream(result["code"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def generate_diagram_stream(prompt: str, strict_latex_only: bool = True, model: str = DEFAULT_MODEL):
    result = generate_diagram(prompt, model=model)
    if result["success"]:
        return _text_to_stream(result["code"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def generate_plot_stream(expression: str, xlabel: str = "x", ylabel: str = "y", title: str = "",
                         model: str = DEFAULT_MODEL):
    result = generate_plot(expression, xlabel, ylabel, title, model)
    if result["success"]:
        return _text_to_stream(result["code"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def fetch_bibtex_stream(identifier: str, model: str = DEFAULT_MODEL):
    result = fetch_bibtex(identifier, model)
    if result["success"]:
        return _text_to_stream(result["code"], chunk_size=5)
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def format_references_stream(references: str, style: str = "ieee", model: str = DEFAULT_MODEL):
    result = format_references(references, style, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def check_citation_stream(citation: str, model: str = DEFAULT_MODEL):
    result = check_citation(citation, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def add_alt_text_stream(figure_code: str, model: str = DEFAULT_MODEL):
    result = add_alt_text(figure_code, model)
    if result["success"]:
        return _text_to_stream(result["result"], chunk_size=5)
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def check_colors_stream(colors: list, palette_type: str = "all", model: str = DEFAULT_MODEL):
    result = check_colors(colors, palette_type, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def check_template_stream(latex_code: str, template: str = "ieee", model: str = DEFAULT_MODEL):
    result = check_template(latex_code, template, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def get_diff_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    result = get_diff(old_text, new_text, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def summarize_changes_stream(old_text: str, new_text: str, model: str = DEFAULT_MODEL):
    result = summarize_changes(old_text, new_text, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"


def summarize_document_stream(latex_code: str, model: str = DEFAULT_MODEL):
    result = summarize_document(latex_code, model)
    if result["success"]:
        return _text_to_stream(result["result"])
    yield f"data: {json.dumps({'error': result.get('error', 'Failed')})}\n\n"