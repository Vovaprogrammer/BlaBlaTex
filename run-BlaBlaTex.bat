@echo off
echo ========================================
echo       BlaBlaTex — Запуск
echo ========================================
echo.

echo 📡 Запуск бэкенда...
start "BlaBlaTex Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate && python -m uvicorn app.main:app --reload"

timeout /t 3 /nobreak >nul

echo 🌐 Запуск фронтенда...
start "BlaBlaTex Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 5 /nobreak >nul

start http://localhost:5173

echo.
echo ✅ BlaBlaTex запущен!
echo.
pause