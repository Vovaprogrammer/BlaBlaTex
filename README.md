# BlaBlaTex

<div align="center">
  <strong>Умный редактор LaTeX с искусственным интеллектом</strong><br>
  Генерация кода, объяснение формул, исправление ошибок и многое другое
</div>

<br>

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Node.js](https://img.shields.io/badge/Node.js-18+-green.svg)](https://nodejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-teal.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-cyan.svg)](https://react.dev)
[![MIT License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 О проекте

BlaBlaTex — это современный онлайн-редактор LaTeX, который использует локальные AI модели для помощи в написании научных и технических документов. Проект полностью бесплатен и работает локально на вашем компьютере.

### Ключевые возможности

- ✍️ **Редактор LaTeX** с подсветкой синтаксиса и автодополнением
- 🤖 **AI Ассистент** на базе Gemma 4 и Qwen 3.5
- 📄 **Предпросмотр PDF** в реальном времени
- 🔧 **Автоисправление** ошибок компиляции
- 📊 **Генерация таблиц** и диаграмм
- 📚 **Библиография** по DOI/arXiv
- 👥 **Совместная работа** над документами

---

## 🚀 Быстрый старт

### 1. Установите Docker Desktop

Скачайте и установите Docker Desktop с официального сайта:  
👉 https://www.docker.com/products/docker-desktop/

Запускайте файл установщика от имени администратора.

### 2. Клонируйте репозиторий

```bash
git clone -b develop https://github.com/Vovaprogrammer/BlaBlaTex.git
cd BlaBlaTex
```

### 3. Настройте переменные окружения

Скопируйте файл .env.example в .env и заполните своими данными:

```bash
cp .env.example .env
```

Что нужно заполнить:

SECRET_KEY — необходимо получить у доверенного лица и вставить в .env

### 4. Скачайте AI модель Gemma 4

🔗 [google_gemma-4-E4B-it-Q4_K_M.gguf](https://huggingface.co/bartowski/google_gemma-4-E4B-it-GGUF/resolve/main/google_gemma-4-E4B-it-Q4_K_M.gguf)

Поместите скачанный файл в папку:  
   
`BlaBlaTex/ollama-models/gemma4/`

### Проверка

```bash
docker exec blablatax-ollama ollama list
```

Должна появиться модель gemma4-e4b.

### 5. Запустите проект

```bash
docker compose up -d
```

### 6. Откройте в браузере

```
http://localhost:5173
```

> 💡 **Первый запуск** может занять 30-40 минут (скачивание образов и зависимостей)  
> 🔄 **Последующие запуски** — 5-10 секунд

---

## 🤖 AI Модели

Модель **Gemma 4 E4B** не входит в стандартную поставку Ollama, поэтому её нужно скачать отдельно. Скачивание модели занимает примерно 10 минут.

> ⚠️ Qwen 3.5 4B скачивается автоматически при первом запуске. Загрузка занимает около 10 минут.

| Модель | Размер | Качество | Скорость |
|--------|--------|----------|----------|
| Gemma 4 E4B | 5.4 GB | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Qwen 3.5 4B | 3.4 GB | ⭐⭐⭐ | ⭐⭐⭐⭐ |

---

## 📁 Структура проекта

```
BlaBlaTex/
├── backend/                 # FastAPI сервер
├── frontend/                # React приложение
├── ollama/                  # Конфигурация Ollama (Dockerfile)
├── ollama-models/           # Локальные модели (GGUF файлы)
├── docker-compose.yml       # Оркестрация сервисов
├── .env                     # Переменные окружения (не в Git)
├── .env.example             # Шаблон переменных
├── .gitignore               # Исключения Git
├── run-docker.bat           # Скрипт запуска для Windows
└── README.md                # Этот файл
```

---

## 👥 Автор

Владимир Чистяков — главный фронтенд-бэкенд разработчик

Владислав Тесля — тестировщик

Холоднов Иван — разработчик

Вершинина Кристина — фронтенд разработчик

---

## 📄 Лицензия

MIT License