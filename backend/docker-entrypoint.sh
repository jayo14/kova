#!/bin/sh
set -e

# Explicit command (for example from docker-compose) wins.
if [ "$#" -gt 0 ]; then exec "$@"; fi

CONC="${WORKER_CONCURRENCY:-1}"
migrate() { if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then alembic upgrade head; fi; }

PREFIX="${CELERY_QUEUE_PREFIX:-}"
QUEUES="${CELERY_QUEUES:-${PREFIX}kova-free,${PREFIX}kova-pro,${PREFIX}kova-enterprise}"

case "${KOVA_ROLE:-all}" in
  api)
    migrate
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" ;;
  worker)
    exec celery -A app.workers.celery_app worker --loglevel=info --concurrency="$CONC" -Q "$QUEUES" ;;
  all)
    migrate
    celery -A app.workers.celery_app worker --loglevel=info --concurrency="$CONC" -Q "$QUEUES" &
    WORKER_PID=$!
    uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
    API_PID=$!
    trap 'kill -TERM $WORKER_PID $API_PID 2>/dev/null' TERM INT
    # If either process dies, exit so the platform restarts the container.
    while kill -0 $WORKER_PID 2>/dev/null && kill -0 $API_PID 2>/dev/null; do sleep 2; done
    kill -TERM $WORKER_PID $API_PID 2>/dev/null || true
    wait
    exit 1 ;;
  *)
    echo "Unknown KOVA_ROLE: ${KOVA_ROLE}" >&2; exit 2 ;;
esac
