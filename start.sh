#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

# Check if .env specifies remote Redis
USE_REMOTE_REDIS=0
if [ -f .env ]; then
    if grep -E "^(REDIS_URL|CELERY_BROKER_URL)=.*(rediss://|db-|rumptycloud|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)" .env >/dev/null 2>&1; then
        USE_REMOTE_REDIS=1
    fi
fi

REDIS_STARTED=0
if [ "$USE_REMOTE_REDIS" -eq 0 ]; then
    if ! pgrep -x redis-server >/dev/null 2>&1; then
        redis-server --daemonize yes
        REDIS_STARTED=1
        echo "Redis started"
    fi
else
    echo "Using remote Redis from .env"
fi

# Kill any leftover or orphaned celery workers before starting
pkill -f "celery -A app.workers.celery_app" 2>/dev/null || true

CELERY_PID=""
UVICORN_PID=""

cleanup() {
    echo "Stopping services..."
    [[ -n "${UVICORN_PID:-}" ]] && kill "$UVICORN_PID" 2>/dev/null || true
    pkill -f "celery -A app.workers.celery_app" 2>/dev/null || true
    if [[ "$REDIS_STARTED" -eq 1 ]]; then
        redis-cli shutdown nosave 2>/dev/null || true
    fi
}
trap cleanup INT TERM EXIT

# Start Celery worker in its own process group with concurrency 1
WORKER_LOG="/tmp/worker.log"
> "$WORKER_LOG"
setsid .venv/bin/celery -A app.workers.celery_app worker --loglevel=info --concurrency=1 -Q kova-free,kova-pro,kova-enterprise > "$WORKER_LOG" 2>&1 &
CELERY_PID=$!
echo "Celery worker started (PID $CELERY_PID, concurrency 1, logs: $WORKER_LOG)"

# Verify worker process is alive
sleep 2
if ! kill -0 "$CELERY_PID" 2>/dev/null; then
    echo "ERROR: Celery worker failed to start. Last logs from $WORKER_LOG:" >&2
    tail -n 25 "$WORKER_LOG" >&2 || true
fi

.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
UVICORN_PID=$!
echo "API server started on http://localhost:8000"

wait
