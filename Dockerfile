FROM python:3.12-slim

# Устанавливаем системные зависимости:
# - chromium и chromium-driver — для undetected-chromedriver
# - xvfb — виртуальный дисплей (замена headless, обходит wasm защиту)
# - прочие зависимости для Chromium
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    xvfb \
    xauth \
    libglib2.0-0 \
    libnss3 \
    libfontconfig1 \
    libxss1 \
    libasound2t64 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости отдельно — используем кэш Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем Playwright браузеры (не используется в prod,
# но может понадобиться для разработки)
# RUN playwright install chromium

# Копируем весь проект
COPY . .

# Создаём папку для логов
RUN mkdir -p logs

# Папка для входных данных (xlsx монтируется через volume)
RUN mkdir -p data

CMD ["python", "main.py", "data/inns.xlsx"]
