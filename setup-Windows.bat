@echo off
chcp 65001 >nul
title BlaBlaTex Setup

echo.
echo ========================================
echo       BlaBlaTex — Установка
echo ========================================
echo.

REM ============================================
REM Проверка и установка Python
REM ============================================
echo [1/5] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo    ❌ Python не найден. Устанавливаем...
    echo.
    winget install Python.Python.3.11 --accept-package-agreements --silent
    if errorlevel 1 (
        echo    ❌ Не удалось установить Python автоматически.
        echo    📥 Скачайте вручную: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo    ✅ Python установлен. Перезапустите скрипт.
    pause
    exit /b 0
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do echo    ✅ Python %%i
echo.

REM ============================================
REM Проверка и установка Node.js
REM ============================================
echo [2/5] Проверка Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo    ❌ Node.js не найден. Устанавливаем...
    echo.
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --silent
    if errorlevel 1 (
        echo    ❌ Не удалось установить Node.js автоматически.
        echo    📥 Скачайте вручную: https://nodejs.org/
        pause
        exit /b 1
    )
    echo    ✅ Node.js установлен. Перезапустите скрипт.
    pause
    exit /b 0
)
for /f "tokens=1" %%i in ('node --version') do echo    ✅ Node.js %%i
echo.

REM ============================================
REM Проверка и установка MiKTeX (LaTeX)
REM ============================================
echo [3/5] Проверка LaTeX...
pdflatex --version >nul 2>&1
if errorlevel 1 (
    echo    ⚠️ LaTeX (MiKTeX) не найден. Устанавливаем...
    echo.
    echo    📥 Скачивание MiKTeX...
    winget install MiKTeX.MiKTeX --accept-package-agreements --silent 2>nul
    if errorlevel 1 (
        echo    ⚠️ Не удалось установить MiKTeX автоматически.
        echo    📥 Скачайте вручную: https://miktex.org/download
        echo    💡 Без LaTeX не будет работать компиляция PDF.
        echo.
        choice /C YN /M "Продолжить установку без LaTeX"
        if errorlevel 2 exit /b 1
    ) else (
        echo    ✅ MiKTeX установлен
    )
) else (
    echo    ✅ LaTeX найден
)
echo.

REM ============================================
REM Создание .env файла (оригинальный код)
REM ============================================
echo [4/5] Настройка окружения...
cd /d %~dp0backend
if not exist .env (
    if exist .env.example (
        echo    📝 Создание .env из .env.example...
        copy .env.example .env >nul
        echo    ✅ .env создан
    ) else (
        echo    ⚠️ Файл .env.example не найден. Создаю базовый...
        echo SUPABASE_URL=http://localhost:8000 > .env
        echo SUPABASE_ANON_KEY=test-anon-key >> .env
        echo GOOGLE_CLIENT_ID=test-client-id >> .env
        echo GOOGLE_CLIENT_SECRET=test-client-secret >> .env
        echo DATABASE_URL=sqlite:///./test.db >> .env
        echo SECRET_KEY=development-secret-key >> .env
        echo ALGORITHM=HS256 >> .env
        echo ACCESS_TOKEN_EXPIRE_MINUTES=30 >> .env
        echo BACKEND_CORS_ORIGINS=["http://localhost:5173"] >> .env
        echo GEMINI_API_KEY=test-gemini-key >> .env
        echo FRONTEND_URL=http://localhost:5173 >> .env
        echo ✅ Базовый .env создан
    )
) else (
    echo    ✅ .env уже существует
)
echo.

REM ============================================
REM Установка зависимостей
REM ============================================
echo [5/5] Установка зависимостей...
echo.

REM Бэкенд
echo    📦 Установка Python зависимостей...
cd /d %~dp0backend
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

REM Фронтенд
echo    📦 Установка Node зависимостей...
cd /d %~dp0frontend
npm install --registry=https://registry.npmmirror.com

echo.
echo ========================================
echo ✅ Установка завершена!
echo.
echo 🚀 Для запуска используйте: run-BlaBlaTex.bat
echo.
echo 📝 Примечание: Если MiKTeX установлен, может потребоваться
echo    перезагрузка компьютера для завершения установки.
echo ========================================
echo.

pause