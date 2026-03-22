#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo "========================================"
echo "      BlaBlaTex — Установка"
echo "========================================"
echo ""

# Получаем директорию скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================
# Проверка и установка Python
# ============================================
echo -e "${BLUE}[1/5] Проверка Python...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}⚠️ Python не найден. Устанавливаем...${NC}"
    
    if command -v apt &> /dev/null; then
        sudo apt update
        sudo apt install -y python3 python3-venv python3-pip
    elif command -v brew &> /dev/null; then
        brew install python3
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y python3 python3-virtualenv python3-pip
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm python python-pip python-virtualenv
    else
        echo -e "${RED}❌ Не удалось определить пакетный менеджер${NC}"
        echo "📥 Скачайте Python вручную: https://www.python.org/downloads/"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Python установлен${NC}"
    echo -e "${YELLOW}🔄 Перезапустите скрипт после установки${NC}"
    exit 0
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✅ $PYTHON_VERSION${NC}"
echo ""

# ============================================
# Проверка и установка Node.js
# ============================================
echo -e "${BLUE}[2/5] Проверка Node.js...${NC}"

if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}⚠️ Node.js не найден. Устанавливаем...${NC}"
    
    if command -v apt &> /dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
        sudo apt install -y nodejs
    elif command -v brew &> /dev/null; then
        brew install node
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y nodejs npm
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm nodejs npm
    else
        echo -e "${RED}❌ Не удалось установить Node.js автоматически${NC}"
        echo "📥 Скачайте вручную: https://nodejs.org/"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Node.js установлен${NC}"
    echo -e "${YELLOW}🔄 Перезапустите скрипт после установки${NC}"
    exit 0
fi

NODE_VERSION=$(node --version)
echo -e "${GREEN}✅ $NODE_VERSION${NC}"
echo ""

# ============================================
# Проверка и установка curl
# ============================================
echo -e "${BLUE}[3/5] Проверка curl...${NC}"

if ! command -v curl &> /dev/null; then
    echo -e "${YELLOW}⚠️ curl не найден. Устанавливаем...${NC}"
    
    if command -v apt &> /dev/null; then
        sudo apt install -y curl
    elif command -v brew &> /dev/null; then
        brew install curl
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y curl
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm curl
    fi
fi
echo -e "${GREEN}✅ curl найден${NC}"
echo ""

# ============================================
# Проверка и установка LaTeX
# ============================================
echo -e "${BLUE}[4/5] Проверка LaTeX...${NC}"

if ! command -v pdflatex &> /dev/null; then
    echo -e "${YELLOW}⚠️ LaTeX не найден. Устанавливаем...${NC}"
    echo "   (может занять 5-10 минут)"
    
    if command -v apt &> /dev/null; then
        sudo apt update
        sudo apt install -y texlive-full texlive-lang-cyrillic
    elif command -v brew &> /dev/null; then
        echo "   🍎 Установка MacTeX (около 4 ГБ)..."
        brew install --cask mactex
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y texlive-scheme-full
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm texlive-most
    else
        echo -e "${YELLOW}⚠️ Не удалось установить LaTeX автоматически${NC}"
        echo "📥 Скачайте вручную:"
        echo "   - Ubuntu/Debian: sudo apt install texlive-full"
        echo "   - macOS: brew install --cask mactex"
        echo "   - Fedora: sudo dnf install texlive-scheme-full"
        echo ""
        read -p "Продолжить без LaTeX? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

if command -v pdflatex &> /dev/null; then
    echo -e "${GREEN}✅ LaTeX найден${NC}"
else
    echo -e "${YELLOW}⚠️ LaTeX не установлен. PDF компиляция не будет работать.${NC}"
fi
echo ""

# ============================================
# Установка зависимостей
# ============================================
echo -e "${BLUE}[5/5] Установка зависимостей...${NC}"
echo ""

# Бэкенд
echo -e "${BLUE}   📦 Установка Python зависимостей...${NC}"
cd "$SCRIPT_DIR/backend"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Фронтенд
echo -e "${BLUE}   📦 Установка Node зависимостей...${NC}"
cd "$SCRIPT_DIR/frontend"
npm install --registry=https://registry.npmmirror.com

# ============================================
# Создание .env файла (если нет)
# ============================================
echo -e "${BLUE}   📝 Создание .env файла...${NC}"
cd "$SCRIPT_DIR/backend"

if [ ! -f ".env" ]; then
    cat > .env << 'EOF'
# Supabase (можно оставить тестовыми для локальной разработки)
SUPABASE_URL=http://localhost:8000
SUPABASE_ANON_KEY=test-anon-key

# Google OAuth (для теста можно любые значения)
GOOGLE_CLIENT_ID=test-client-id
GOOGLE_CLIENT_SECRET=test-client-secret

# Database (SQLite для разработки)
DATABASE_URL=sqlite:///./test.db

# Security
SECRET_KEY=development-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
BACKEND_CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]

# AI Settings
GEMINI_API_KEY=test-gemini-key

# Frontend URL для редиректов
FRONTEND_URL=http://localhost:5173
REDIRECT_URL=http://localhost:5173
OAUTH_REDIRECT_URL=http://localhost:8000/auth/callback
EOF
    echo -e "${GREEN}   ✅ .env файл создан${NC}"
else
    echo -e "${GREEN}   ✅ .env файл уже существует${NC}"
fi

echo ""
echo "========================================"
echo -e "${GREEN}✅ Установка завершена!${NC}"
echo ""
echo "🚀 Для запуска используйте: ./run-BlaBlaTex.sh"
echo "   (или ./run-wsl.sh для WSL)"
echo "========================================"
echo ""

read -p "Нажмите Enter для выхода..."