@echo off
chcp 65001 >nul
title BlaBlaTex Setup & Launcher

echo.
echo ========================================
echo       BlaBlaTex — Установка и запуск
echo ========================================
echo.

REM ============================================
REM Проверка и установка Python
REM ============================================
echo [1/6] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo    ❌ Python не найден. Устанавливаем...
    echo.
    echo    📥 Скачивание Python...
    winget install Python.Python.3.11 --accept-package-agreements --silent
    if errorlevel 1 (
        echo    ❌ Не удалось установить Python автоматически.
        echo    📥 Скачайте вручную: https://www.python.org/downloads/
        echo    ⚠️  При установке отметьте "Add Python to PATH"
        pause
        exit /b 1
    )
    echo    ✅ Python установлен
    echo    🔄 Перезапустите скрипт после установки
    pause
    exit /b 0
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do echo    ✅ Python %%i
echo.

REM ============================================
REM Проверка и установка Node.js
REM ============================================
echo [2/6] Проверка Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo    ❌ Node.js не найден. Устанавливаем...
    echo.
    echo    📥 Скачивание Node.js LTS...
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --silent
    if errorlevel 1 (
        echo    ❌ Не удалось установить Node.js автоматически.
        echo    📥 Скачайте вручную: https://nodejs.org/
        pause
        exit /b 1
    )
    echo    ✅ Node.js установлен
    echo    🔄 Перезапустите скрипт после установки
    pause
    exit /b 0
)
for /f "tokens=1" %%i in ('node --version') do echo    ✅ Node.js %%i
echo.

REM ============================================
REM Проверка и установка Git
REM ============================================
echo [3/6] Проверка Git...
git --version >nul 2>&1
if errorlevel 1 (
    echo    ⚠️ Git не найден. Устанавливаем...
    echo.
    echo    📥 Скачивание Git...
    winget install Git.Git --accept-package-agreements --silent
    if errorlevel 1 (
        echo    ⚠️ Git не установлен. Это не критично, можно скачать ZIP архив.
    ) else (
        echo    ✅ Git установлен
    )
) else (
    echo    ✅ Git найден
)
echo.

REM ============================================
REM Проверка и установка LaTeX (MiKTeX)
REM ============================================
echo [4/6] Проверка LaTeX...
pdflatex --version >nul 2>&1
if errorlevel 1 (
    echo    ⚠️ LaTeX не найден. Установка MiKTeX...
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
REM Проверка портов
REM ============================================
echo [5/6] Проверка портов...
netstat -ano | findstr :8000 >nul
if not errorlevel 1 (
    echo    ⚠️ Порт 8000 занят. Возможно, бэкенд уже запущен.
)
netstat -ano | findstr :5173 >nul
if not errorlevel 1 (
    echo    ⚠️ Порт 5173 занят. Возможно, фронтенд уже запущен.
)
echo.

REM ============================================
REM Установка зависимостей и запуск
REM ============================================
echo [6/6] Установка зависимостей и запуск...
echo.

echo 📡 Запуск бэкенда (http://localhost:8000)...
start "BlaBlaTex Backend" cmd /k "cd /d %~dp0backend && if not exist venv (python -m venv venv) && venv\Scripts\activate && echo 📦 Установка Python пакетов... && pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple && echo ✅ Бэкенд запущен && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

timeout /t 5 /nobreak >nul

echo 🌐 Запуск фронтенда (http://localhost:5173)...
start "BlaBlaTex Frontend" cmd /k "cd /d %~dp0frontend && echo 📦 Установка Node пакетов... && npm install --registry=https://registry.npmmirror.com && echo ✅ Фронтенд запущен && npm run dev"

timeout /t 8 /nobreak >nul

echo.
echo ========================================
echo ✅ BlaBlaTex успешно установлен и запущен!
echo.
echo 📝 Редактор: http://localhost:5173
echo 🔧 Бэкенд:  http://localhost:8000
echo.
echo 💡 Чтобы остановить, закройте окна терминалов
echo ========================================
echo.

start http://localhost:5173

pause