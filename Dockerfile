FROM python:3.12-slim

WORKDIR /app

# Install system deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
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
    libpango-1.0-0 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=100 --retries=5 --prefer-binary . \
    && pip install celery redis --no-cache-dir

# Install Playwright browsers
RUN playwright install chromium

EXPOSE 8000

# Support multiple launch modes via ENV:
#   CMD="api"       → uvicorn app.main:app (default)
#   CMD="worker"    → celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
#   CMD="all"       → start redis + api + worker (use with docker compose)
ENV CMD="api"

# Default: API server
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
