@echo off
chcp 65001 >nul
title BlaBlaTex Launcher

echo.
echo ========================================
echo       BlaBlaTex — Запуск
echo ========================================
echo.

REM Проверка, что всё установлено
if not exist "%~dp0backend\venv" (
    echo ❌ Виртуальное окружение не найдено!
    echo 💡 Сначала запустите: setup-BlaBlaTex.bat
    pause
    exit /b 1
)

echo 📡 Запуск бэкенда (http://localhost:8000)...
echo    Логи будут отображаться в отдельном окне
echo.

start "BlaBlaTex Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate && python -m uvicorn app.main:app --reload"

timeout /t 3 /nobreak >nul

echo 🌐 Запуск фронтенда (http://localhost:5173)...
start "BlaBlaTex Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 5 /nobreak >nul

echo 📂 Открытие браузера...
start http://localhost:5173

echo.
echo ========================================
echo ✅ BlaBlaTex запущен!
echo.
echo 📝 Редактор: http://localhost:5173
echo 🔧 Бэкенд:  http://localhost:8000
echo.
echo 💡 Для остановки закройте оба окна терминалов
echo ========================================
echo.

pause