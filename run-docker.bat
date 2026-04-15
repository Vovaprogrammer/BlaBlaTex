@echo off
chcp 65001 >nul
title BlaBlaTex Docker Launcher

echo.
echo ========================================
echo       BlaBlaTex — Docker запуск
echo ========================================
echo.

REM Проверка Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker не найден!
    echo.
    echo 📥 Скачайте Docker Desktop:
    echo    https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

echo ✅ Docker найден
echo.

REM Проверка .env.docker
if not exist .env.docker (
    echo ⚠️ Файл .env.docker не найден!
    echo.
    echo 📝 Создайте .env.docker из шаблона:
    echo    copy .env.docker.example .env.docker
    echo.
    echo 💡 Затем добавьте ваши SUPABASE_URL и SUPABASE_ANON_KEY
    echo.
    pause
    exit /b 1
)

REM Загрузка переменных окружения
setlocal enabledelayedexpansion
for /f "usebackq tokens=*" %%i in (.env.docker) do set %%i

echo 🚀 Сборка и запуск контейнеров...
docker-compose up -d --build

echo.
echo ========================================
echo ✅ BlaBlaTex запущен через Docker!
echo.
echo 📝 Редактор: http://localhost:5173
echo 🔧 Бэкенд:  http://localhost:8000
echo.
echo 💡 Для остановки: docker-compose down
echo ========================================
echo.

timeout /t 3 /nobreak >nul
start http://localhost:5173

pause