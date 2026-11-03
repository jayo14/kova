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

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create non-root user for runtime
RUN groupadd -r kova && useradd -r -g kova -m -d /home/kova kova && \
    chown -R kova:kova /app /home/kova

# Playwright browsers already installed; ensure profile dir
RUN mkdir -p /tmp/kova-browser-profile && chown -R kova:kova /tmp/kova-browser-profile

USER kova
ENV KOVA_ROLE=api
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
