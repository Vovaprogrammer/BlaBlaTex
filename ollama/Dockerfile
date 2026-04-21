FROM ollama/ollama:latest

# Устанавливаем необходимые пакеты
RUN apt-get update && apt-get install -y curl net-tools && rm -rf /var/lib/apt/lists/*

# Создаём модель Gemma 4 (только при сборке, если файлы существуют)
RUN mkdir -p /root/.ollama/models/gemma4 && \
    if [ -f /models/gemma4/google_gemma-4-E4B-it-Q4_K_M.gguf ] && [ -f /models/gemma4/Modelfile ]; then \
        cp /models/gemma4/google_gemma-4-E4B-it-Q4_K_M.gguf /root/.ollama/models/gemma4/ && \
        cp /models/gemma4/Modelfile /root/.ollama/models/gemma4/ && \
        cd /root/.ollama/models/gemma4 && \
        echo "Creating Gemma 4 model (this may take 30-60 seconds)..." && \
        ollama create gemma4-e4b -f ./Modelfile && \
        touch /root/.ollama/models/gemma4/.imported && \
        echo "✅ Gemma 4 model created successfully"; \
    else \
        echo "⚠️ Gemma 4 model files not found, skipping creation"; \
    fi

# НЕТ CMD — используем CMD из родительского образа ollama/ollama:latest