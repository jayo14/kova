# Local Setup

## Prerequisites

- Python 3.12+ (https://www.python.org/downloads/)
- Node.js 20+ and npm (https://nodejs.org/)
- PostgreSQL 16 (or use Docker)
- Redis 7 (or use Docker)
- Git

Optional: AI provider keys (OpenRouter/Gemini/Groq/NVIDIA) for agent features.

## Recommended: Docker Compose

```bash
cp .env.example backend/.env
docker compose up -d
```

Open http://localhost:3000 and http://localhost:8000/health.

## Manual setup

### Backend

```bash
cd backend
python3 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .
playwright install chromium
cp ../.env.example .env  # then edit
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd backend
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local  # if exists; else create with NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000.

## Environment variables

Required: DATABASE_URL, REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND, JWT_SECRET_KEY.
Optional: AI_* keys, SUPABASE_* (external storage/auth), STORAGE_BUCKET_PREFIX.

## Stop / reset

```bash
# docker
docker compose down
docker compose down -v  # reset data
# manual: Ctrl+C processes; drop/recreate DB for reset
```
