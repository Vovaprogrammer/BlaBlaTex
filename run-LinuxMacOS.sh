#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo "========================================"
echo "      BlaBlaTex — Запуск"
echo "========================================"
echo ""

# Получаем директорию скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Проверка, что всё установлено
if [ ! -d "$SCRIPT_DIR/backend/venv" ]; then
    echo -e "${RED}❌ Виртуальное окружение не найдено!${NC}"
    echo -e "${YELLOW}💡 Сначала запустите: ./setup-BlaBlaTex.sh${NC}"
    exit 1
fi

# Проверка наличия .env
if [ ! -f "$SCRIPT_DIR/backend/.env" ]; then
    echo -e "${YELLOW}⚠️ .env файл не найден!${NC}"
    echo -e "${YELLOW}💡 Сначала запустите: ./setup-BlaBlaTex.sh${NC}"
    exit 1
fi

# Проверка портов
check_port() {
    if lsof -i :$1 &> /dev/null; then
        echo -e "${YELLOW}⚠️ Порт $1 уже занят${NC}"
        return 1
    fi
    return 0
}

check_port 8000
check_port 5173
echo ""

# Запуск бэкенда
echo -e "${BLUE}📡 Запуск бэкенда (http://localhost:8000)...${NC}"
echo -e "${BLUE}   Логи будут отображаться в отдельном окне${NC}"
echo ""

# Открываем новое окно терминала для бэкенда
if command -v gnome-terminal &> /dev/null; then
    gnome-terminal --title="BlaBlaTex Backend" -- bash -c "cd '$SCRIPT_DIR/backend' && source venv/bin/activate && python -m uvicorn app.main:app --reload; echo 'Нажмите Enter для закрытия...'; read"
elif command -v konsole &> /dev/null; then
    konsole --new-tab --title "BlaBlaTex Backend" -e bash -c "cd '$SCRIPT_DIR/backend' && source venv/bin/activate && python -m uvicorn app.main:app --reload; echo 'Нажмите Enter для закрытия...'; read"
elif command -v xterm &> /dev/null; then
    xterm -title "BlaBlaTex Backend" -e bash -c "cd '$SCRIPT_DIR/backend' && source venv/bin/activate && python -m uvicorn app.main:app --reload; echo 'Нажмите Enter для закрытия...'; read" &
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    osascript -e "tell application \"Terminal\" to do script \"cd '$SCRIPT_DIR/backend' && source venv/bin/activate && python -m uvicorn app.main:app --reload\""
else
    # Если нет графического терминала (WSL без GUI), запускаем в фоне
    echo -e "${YELLOW}⚠️ Не удалось открыть отдельное окно. Запуск в фоне...${NC}"
    cd "$SCRIPT_DIR/backend"
    source venv/bin/activate
    python -m uvicorn app.main:app --reload &
    BACKEND_PID=$!
    cd "$SCRIPT_DIR"
fi

sleep 3

# Запуск фронтенда
echo -e "${BLUE}🌐 Запуск фронтенда (http://localhost:5173)...${NC}"
echo ""

if command -v gnome-terminal &> /dev/null; then
    gnome-terminal --title="BlaBlaTex Frontend" -- bash -c "cd '$SCRIPT_DIR/frontend' && npm run dev; echo 'Нажмите Enter для закрытия...'; read"
elif command -v konsole &> /dev/null; then
    konsole --new-tab --title "BlaBlaTex Frontend" -e bash -c "cd '$SCRIPT_DIR/frontend' && npm run dev; echo 'Нажмите Enter для закрытия...'; read"
elif command -v xterm &> /dev/null; then
    xterm -title "BlaBlaTex Frontend" -e bash -c "cd '$SCRIPT_DIR/frontend' && npm run dev; echo 'Нажмите Enter для закрытия...'; read" &
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    osascript -e "tell application \"Terminal\" to do script \"cd '$SCRIPT_DIR/frontend' && npm run dev\""
else
    # Если нет графического терминала (WSL без GUI), запускаем в фоне
    echo -e "${YELLOW}⚠️ Не удалось открыть отдельное окно. Запуск в фоне...${NC}"
    cd "$SCRIPT_DIR/frontend"
    npm run dev &
    FRONTEND_PID=$!
    cd "$SCRIPT_DIR"
fi

sleep 5

# Открытие браузера
echo -e "${BLUE}📂 Открытие браузера...${NC}"
if command -v open &> /dev/null; then
    open http://localhost:5173
elif command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:5173
else
    echo -e "${YELLOW}⚠️ Не удалось открыть браузер автоматически${NC}"
    echo "   Перейдите по ссылке: http://localhost:5173"
fi

echo ""
echo "========================================"
echo -e "${GREEN}✅ BlaBlaTex запущен!${NC}"
echo ""
echo "📝 Редактор: http://localhost:5173"
echo "🔧 Бэкенд:  http://localhost:8000"
echo ""
echo "💡 Для остановки закройте окна терминалов"
echo "========================================"
echo ""

read -p "Нажмите Enter для выхода..."