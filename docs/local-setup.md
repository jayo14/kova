# Local Setup Guide

This guide walks you through setting up and running Kova locally on Linux, macOS, or Windows.

---

## 1. Prerequisites & Version Requirements

| Dependency | Minimum Version | Installation Link | Notes |
| :--- | :--- | :--- | :--- |
| **Docker & Docker Compose** | Docker 24.0+, Compose v2 | [docker.com/get-started](https://www.docker.com/get-started/) | Recommended path. Runs API, Worker, Redis, and UI. |
| **Python** | 3.12+ (tested up to 3.14) | [python.org/downloads](https://www.python.org/downloads/) | Required for manual backend setup. |
| **Node.js & npm** | Node 20 LTS+, npm 10+ | [nodejs.org](https://nodejs.org/) | Required for manual frontend setup. |
| **PostgreSQL** | 16+ | [postgresql.org/download](https://www.postgresql.org/download/) | Can be run via Docker or managed service (e.g. Neon, Supabase). |
| **Redis** | 7+ | [redis.io/download](https://redis.io/download/) | Used for task queue and live viewport frames. |

---

## 2. Recommended: Docker Compose Setup

Docker Compose runs the complete stack with isolated networks and proper volume mounts.

### Step 1: Clone the Repository
```bash
git clone https://github.com/jayo14/kova.git
cd kova
```

### Step 2: Configure Environment
Copy the example environment configuration to `backend/.env`:
```bash
cp .env.example backend/.env
```

Open `backend/.env` in your editor. For local Docker testing without external services, configure the minimal required variables:
```ini
ENVIRONMENT=development
DEBUG=true

# Database (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/kova

# Redis (Celery broker on db 1, ephemeral frames on db 0)
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Security Secrets (Generate random 32+ char strings for local use)
JWT_SECRET_KEY=local-dev-jwt-secret-key-must-be-at-least-32-chars-long
CREDENTIAL_ENCRYPTION_KEY=local-dev-encryption-key-32chars!!

# Optional: Add an AI provider key to enable AI-powered journey synthesis
# (If omitted, deterministic exploration and rule-based testing remain functional)
GEMINI_API_KEY=
# or
OPENROUTER_API_KEY=
```

### Step 3: Launch Services
```bash
docker compose up -d --build
```

### Step 4: Verify Service Health
```bash
docker compose ps
curl -fsS http://localhost:8000/health
```
Expected response:
```json
{"status":"healthy","database":"connected","redis":"connected"}
```

Access points:
- **Web Dashboard**: [http://localhost:3000](http://localhost:3000)
- **FastAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **API Health Endpoint**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 3. Manual Local Setup (Development Mode)

Follow this path if you are developing directly on the codebase without Docker.

### A. Start Infrastructure Services
You need a running PostgreSQL and Redis instance. You can start just the data services using Docker:
```bash
docker run -d --name kova-postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=kova postgres:16-alpine
docker run -d --name kova-redis -p 6379:6379 redis:7-alpine
```

### B. Backend API Setup

1. **Navigate to the backend directory and set up a virtual environment**:
   ```bash
   cd backend
   python3 -m venv .venv
   ```

   **Activate virtual environment**:
   - **Linux / macOS**:
     ```bash
     source .venv/bin/activate
     ```
   - **Windows (PowerShell)**:
     ```powershell
     .venv\Scripts\Activate.ps1
     ```
   - **Windows (cmd.exe)**:
     ```cmd
     .venv\Scripts\activate.bat
     ```

2. **Install dependencies and Playwright Chromium**:
   ```bash
   pip install -e .
   playwright install chromium
   ```

   *Linux Users*: If you encounter missing browser shared libraries, install system dependencies:
   ```bash
   playwright install-deps chromium
   ```

3. **Configure Environment**:
   ```bash
   cp ../.env.example .env
   ```
   Ensure `DATABASE_URL` points to your PostgreSQL instance:
   `postgresql+asyncpg://postgres:postgres@localhost:5432/kova`

4. **Run Database Migrations**:
   ```bash
   alembic upgrade head
   ```

5. **Start the FastAPI Server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### C. Celery Execution Worker Setup

In a separate terminal with the `.venv` activated:
```bash
cd backend
source .venv/bin/activate  # Or Windows equivalent
# Default to concurrency=1 for local development to prevent Chromium process contention
celery -A app.workers.celery_app worker --loglevel=info --concurrency=1
```

### D. Frontend Setup

In another terminal:
1. **Navigate to frontend directory**:
   ```bash
   cd frontend
   npm install
   ```
2. **Configure Frontend Environment**:
   Create `frontend/.env.local`:
   ```bash
   echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
   ```
3. **Start Next.js Development Server**:
   ```bash
   npm run dev
   ```
   Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 4. Platform-Specific Notes

### Linux
- Ensure your user has permissions to run Docker or is in the `docker` group (`sudo usermod -aG docker $USER`).
- If running Celery natively without Docker, ensure sufficient shared memory (`/dev/shm`) for Chromium instances.

### macOS
- Apple Silicon (M1/M2/M3/M4) users: Playwright Chromium runs natively on `arm64`. Ensure Docker Desktop is configured with Rosetta 2 emulation enabled if building x86-targeted containers.
- If port `5432` or `6379` is already in use by Homebrew services, stop them via `brew services stop postgresql` / `brew services stop redis`.

### Windows
- Run commands inside **PowerShell** or **WSL2 (Windows Subsystem for Linux)**. WSL2 with Ubuntu is strongly recommended for native execution.
- If using Docker Desktop for Windows, ensure the WSL2 backend is selected in Docker Desktop settings.
- For manual Celery execution on Windows: Celery's `prefork` pool is not supported on Windows. Run Celery with the solo or threads pool:
  ```powershell
  celery -A app.workers.celery_app worker --loglevel=info -P solo
  ```

---

## 5. Stop, Restart, and Clean Up

### Stopping Docker Services
```bash
# Stop all containers
docker compose stop

# Stop and remove containers and networks
docker compose down

# Stop and reset all local database and Redis volumes
docker compose down -v
```

### Inspecting Service Logs
```bash
# Follow all logs
docker compose logs -f

# Follow worker logs (browser execution and journeys)
docker compose logs -f kova-worker

# Follow API gateway logs
docker compose logs -f kova-api
```
