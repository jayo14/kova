# Kova

> Autonomous software-use and product-flow execution platform.

Kova gives software products an autonomous user. Provide a URL, credentials, and a goal — Kova opens an isolated Playwright browser, explores the application, discovers workflows, executes product journeys, and records verifiable step-by-step execution evidence.

---

## Features

- **Autonomous Exploration**: Navigates web applications, detects barriers, identifies user roles, and synthesizes candidate test missions.
- **Resilient Authentication**: Intelligently handles modern SPA login flows (React/Next.js/Supabase/Auth0) with unified locators, synthetic event dispatching, and targeted alert detection.
- **Live Agent Browser Viewport**: Streams real-time Playwright viewport snapshots and browser telemetry directly to the frontend.
- **Flow Execution Engine**: Deterministic action runner supporting clicks, keyboard typing, selects, scrolling, file uploads, and assertion checks with automatic retry logic.
- **Structured Evidence**: Records audit logs, network requests, and visual step-by-step evidence stored securely in Supabase Storage.

---

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, Playwright, SQLAlchemy 2.0 (asyncpg), PostgreSQL, Pydantic v2.
- **Frontend**: Next.js 16 (Turbopack, App Router), TypeScript, Tailwind CSS, Radix UI, Lucide Icons.
- **Storage & Auth**: Supabase (PostgreSQL, Storage, Auth).

---

## Getting Started

### Prerequisites

- Python 3.12 or higher
- Node.js 20 or higher & `npm`
- PostgreSQL instance or Supabase project

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
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/kova
JWT_SECRET_KEY=your-secret-key-at-least-32-chars
ENVIRONMENT=development
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_STORAGE_BUCKET=evidence
```

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

---

## Testing

```bash
# Backend unit & integration tests (requires Redis on :6379 and Postgres on :5432)
cd backend
pytest

# Frontend build & typecheck
cd frontend
npm run build
```

The journey E2E suite (`backend/tests/integration/test_journey_scenarios.py`) runs the real
FlowRunner → Playwright → Verifier pipeline against a deterministic fixture app and asserts
truthful outcomes for auth, search, empty-results, resource, form, false-success, malformed
condition, takeover, and cancellation scenarios.

---

## Deployment Topology

Kova runs as four cooperating processes. The runtime topology is explicit — there is no
hidden worker:

```text
frontend (Next.js)  ──HTTP/WS──>  kova-api (FastAPI: REST + SSE + WS gateway)
                                      │
                                      ├── Celery broker ──> redis (db 1)
                                      ├── frames/control ──> redis (db 0)
                                      └── data/evidence ──> postgres (or external Supabase)
                                      │
                                      ▼
                                 kova-worker (Celery — owns ALL Chromium instances)
```

### One-command start (Docker)

```bash
cp backend/.env.example backend/.env   # set SUPABASE_PROJECT_REF + SUPABASE_SERVICE_ROLE_KEY
docker compose up --build
```

Services: `kova-api` (:8000, runs `alembic upgrade head` then uvicorn),
`kova-worker` (Celery, `--concurrency=2`), `kova-frontend` (:3000), plus `postgres` and
`redis`. External: Supabase for auth JWTs and evidence storage.

### Manual start

```bash
# 1. Data stores (or use managed Postgres/Redis)
docker compose up -d postgres redis

# 2. API (applies migrations first)
cd backend && alembic upgrade head
uvicorn app.main:app --port 8000

# 3. Worker — REQUIRED for execution. Without it, executions stay CREATED.
cd backend
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

# 4. Frontend
cd frontend && npm run dev
```

### Resource expectations

- Each execution = one isolated Chromium context inside the worker: budget ~1–1.5 GB RAM.
- Worker concurrency `2` → at most 2 concurrent browsers (~2–3 GB total for the worker).
- Per-user concurrency is additionally capped in the API (`MAX_ACTIVE_EXECUTIONS_PER_USER = 5`);
  executions above the cap stay `CREATED` (queued) until active runs finish.
- Live viewport frames are ephemeral (~4 FPS JPEG via Redis) and never persisted; evidence
  screenshots are captured separately at verification/failure time.

### Security notes

- The dev auth bypass (shared `dev@kova.local` user) is active ONLY when
  `ENVIRONMENT != production`. In production, `SUPABASE_PROJECT_REF` must be configured or
  the API refuses to issue identities.
- Evidence screenshots live in a private Supabase bucket; access is via short-lived signed
  URLs behind ownership-checked endpoints.
- SSRF protection blocks private ranges, cloud metadata endpoints, and re-checks redirect
  destinations before navigation.

---

## License

Private / Proprietary. All rights reserved.
