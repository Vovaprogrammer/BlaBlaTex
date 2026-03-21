# 📝 BlaBlaTex

**Умный редактор LaTeX** с искусственным интеллектом для научных статей, дипломных работ и академических документов.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Node.js](https://img.shields.io/badge/Node.js-18+-green.svg)](https://nodejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-teal.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-cyan.svg)](https://react.dev)
[![MIT License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ Возможности

- **📝 Редактор** — подсветка синтаксиса, предпросмотр PDF, управление документами
- **🤖 AI Помощник** — генерация LaTeX кода, объяснение фрагментов, автоматическое исправление ошибок
- **📐 Математика** — проверка уравнений, символьные вычисления, проверка размерностей
- **📊 Графика** — автогенерация таблиц, графиков, TikZ диаграмм
- **📚 Библиография** — получение BibTeX по DOI/arXiv, проверка цитирований
- **♿ Доступность** — генерация alt-текста, проверка цветовой слепоты
- **👥 Совместная работа** — сравнение версий, AI-слияние изменений, комментарии

---

## 🚀 Быстрый старт (Windows)

### 1. Установите необходимое ПО (один раз)

- **[Python 3.10+](https://www.python.org/downloads/)** — при установке ОБЯЗАТЕЛЬНО отметьте ✅ **"Add Python to PATH"**
- **[Node.js 18+](https://nodejs.org/)** — рекомендуется LTS версия
- **[Git](https://git-scm.com/downloads)** — не обязательно, можно скачать ZIP архив

### 2. Скачайте и запустите проект

```bash
git clone https://github.com/Vovaprogrammer/BlaBlaTex.git
cd BlaBlaTex
start-BlaBlaTex.bat
```

После запуска браузер автоматически откроется по адресу http://localhost:5173

---

## 🛠️ Ручная установка (если start-BlaBlaTex.bat не работает)

### Бэкенд (Python/FastAPI)

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Бэкенд запустится на: http://localhost:8000

### Фронтенд (React/TypeScript)

```bash
cd frontend
npm install
npm run dev
```

Фронтенд запустится на: http://localhost:5173

---

## 🐧 Для пользователей Linux / macOS

```bash
# Бэкенд
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Фронтенд (в новом терминале)
cd frontend
npm install
npm run dev
```

---

## ⚠️ Решение проблем

### Проблемы с Python

| Проблема | Решение |
|----------|--------|
| `python` не найден | Переустановите Python, отметив галочку "Add Python to PATH" |
| `pip install` таймаут | Используйте зеркало: `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `No module named ...` | Активируйте виртуальное окружение: `venv\Scripts\activate` |

### Проблемы с Node.js

| Проблема | Решение |
|----------|--------|
| `node` не найден | Установите Node.js с официального сайта и перезапустите терминал |
| `npm install` таймаут | Используйте зеркало: `npm install --registry=https://registry.npmmirror.com` |
| `module not found` | Удалите папку `node_modules` и выполните `npm install` заново |

### Проблемы с компиляцией LaTeX

| Проблема | Решение |
|----------|--------|
| UTF-8 decode error | Сохраняйте файлы в кодировке UTF-8 (VS Code: Файл → Сохранить с кодировкой → UTF-8) |
| Missing packages | Установите дистрибутив LaTeX: MiKTeX (Windows) или `sudo apt install texlive-full` (Linux) |

---

## 📁 Структура проекта

```
BlaBlaTex/
├── backend/                 # FastAPI сервер
│   ├── app/
│   │   ├── api/            # API эндпоинты
│   │   ├── core/           # Конфигурация
│   │   ├── services/       # Бизнес-логика
│   │   └── main.py         # Точка входа
│   └── requirements.txt    # Python зависимости
├── frontend/               # React приложение
│   ├── src/
│   │   ├── components/     # UI компоненты
│   │   ├── hooks/          # React хуки
│   │   ├── services/       # API вызовы
│   │   └── App.tsx         # Главный компонент
│   └── package.json        # Node зависимости
├── start-BlaBlaTex.bat               # Скрипт быстрого запуска (Windows)
├── .gitignore              # Исключения для Git
└── README.md               # Этот файл
```

---

## 👥 Команда

Владимир Чистяков — разработчик

---

## 📄 Лицензия

Проект распространяется под лицензией MIT — подробности в файле LICENSE

---

## 🙏 Благодарности

Создано с помощью FastAPI и React

AI функции используют Google Gemini и SymPy