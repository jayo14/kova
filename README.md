# Kova

> Autonomous software-use and product-flow execution platform.

Kova gives software products an autonomous user. Provide a URL, credentials, and a goal — Kova opens an isolated Playwright browser, explores the application, discovers workflows, executes product journeys, and records verifiable step-by-step execution evidence.

---

## Features

- **Autonomous Exploration**: Navigates web applications, detects barriers, identifies user roles, and synthesizes candidate test missions.
- **Resilient Authentication**: Intelligently handles modern SPA login flows with unified locators, synthetic event dispatching, and targeted alert detection.
- **Live Agent Browser Viewport**: Streams real-time Playwright viewport snapshots and browser telemetry directly to the frontend.
- **Flow Execution Engine**: Deterministic action runner supporting clicks, keyboard typing, selects, scrolling, file uploads, and assertion checks with automatic retry logic.
- **Structured Evidence**: Records audit logs, network requests, and visual step-by-step evidence stored securely in S3-compatible storage.

---

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, Playwright, SQLAlchemy 2.0 (asyncpg), PostgreSQL, Pydantic v2.
- **Frontend**: Next.js 16 (Turbopack, App Router), TypeScript, Tailwind CSS, Radix UI, Lucide Icons.
- **Storage & Auth**: RumptyCloud (Managed PostgreSQL, S3 Buckets, Redis) + Custom JWT Authentication.

---

## Getting Started

### Prerequisites

- Python 3.12 or higher
- Node.js 20 or higher & `npm`
- PostgreSQL instance and Redis (or RumptyCloud account)

### 1. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
playwright install chromium

# Configure environment variables
cp .env.example .env
# Edit .env with your RumptyCloud credentials (see below)

# Run database migrations
alembic upgrade head

# Start FastAPI server
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Configure environment variables
cp .env.example .env.local

# Start Next.js development server
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000) to open the Kova dashboard.

---

## Environment Variables

### Backend (`backend/.env`)

```env
# Database (RumptyCloud Managed Postgres)
DATABASE_URL=postgresql+asyncpg://user:password@pg-instance.rumptycloud.com:5432/kova_db

# RumptyCloud Storage (S3-compatible)
RUMPTYCLOUD_S3_ENDPOINT=https://s3.rumptycloud.com
RUMPTYCLOUD_ACCESS_KEY_ID=YOUR_ACCESS_KEY
RUMPTYCLOUD_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
RUMPTYCLOUD_BUCKET_NAME=assets-your-workspace-bucket
RUMPTYCLOUD_PUBLIC_URL_PREFIX=https://assets.rumptycloud.app/projects/your-project-id
STORAGE_BUCKET_PREFIX=kova

# Custom Auth
JWT_SECRET_KEY=your-secure-random-string

# Redis
REDIS_URL=rediss://default:password@redis-instance.rumptycloud.com:30901/0
CELERY_BROKER_URL=rediss://default:password@redis-instance.rumptycloud.com:30901/1
CELERY_RESULT_BACKEND=rediss://default:password@redis-instance.rumptycloud.com:30901/2
```

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Deployment Topology

Kova runs as four cooperating processes. The runtime topology is explicit — there is no
hidden worker:

```text
frontend (Next.js)  ──HTTP/WS──>  kova-api (FastAPI: REST + SSE + WS gateway)
                                      │
                                      ├── Celery broker ──> redis (db 1)
                                      ├── frames/control ──> redis (db 0)
                                      └── data/evidence ──> postgres & S3 Storage
                                      │
                                      ▼
                                 kova-worker (Celery — owns ALL Chromium instances)
```

### Manual start

```bash
# 1. API (applies migrations first)
cd backend && alembic upgrade head
uvicorn app.main:app --port 8000

# 2. Worker — REQUIRED for execution. Without it, executions stay CREATED.
cd backend
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

# 3. Frontend
cd frontend && npm run dev
```

### Resource expectations

- Each execution = one isolated Chromium context inside the worker: budget ~1–1.5 GB RAM.
- Worker concurrency `2` → at most 2 concurrent browsers (~2–3 GB total for the worker).
- Live viewport frames are ephemeral (~4 FPS JPEG via Redis) and never persisted; evidence
  screenshots are captured separately at verification/failure time and uploaded to RumptyCloud S3.

---

## License

Private / Proprietary. All rights reserved.
