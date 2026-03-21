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
echo [1/3] Проверка Python...
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
echo [2/3] Проверка Node.js...
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
REM Установка зависимостей
REM ============================================
echo [3/3] Установка зависимостей...
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
echo ========================================
echo.

pause