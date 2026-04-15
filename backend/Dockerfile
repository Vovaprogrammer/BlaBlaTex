FROM python:3.11-slim

# Установка системных зависимостей и LaTeX
RUN apt-get update && apt-get install -y \
    texlive-full \
    texlive-lang-cyrillic \
    texlive-xetex \
    latexmk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Копирование кода
COPY . .

# Создание папок для временных файлов
RUN mkdir -p /app/temp /app/uploads /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]