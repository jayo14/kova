# Troubleshooting Guide

This guide covers verified failure modes, diagnostics, and remedies for common installation and runtime issues.

---

## 1. Port Conflicts

### Symptoms
`Bind for 0.0.0.0:8000 failed: port is already allocated` or `listen EADDRINUSE: address already in use :::3000`.

### Diagnostic & Remedy
- **Find the offending process**:
  - **Linux / macOS**:
    ```bash
    lsof -i :8000   # Check backend API port
    lsof -i :3000   # Check frontend UI port
    lsof -i :6379   # Check Redis port
    lsof -i :5432   # Check PostgreSQL port
    ```
  - **Windows (PowerShell)**:
    ```powershell
    Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess
    ```
- **Remedy**:
  - Terminate the conflicting process, or modify mapped host ports in `docker-compose.yml` (e.g., change `"8000:8000"` to `"8001:8000"`).

---

## 2. Browser Execution & Worker Issues

### Symptom: Executions Remain in `CREATED` State Indefinitely
The dashboard shows an execution stuck in `CREATED` without moving to `RUNNING`.

### Cause
The Celery worker (`kova-worker`) is not running or cannot connect to the Redis broker queue (`db 1`).

### Diagnostic
1. Inspect worker status:
   ```bash
   docker compose ps kova-worker
   docker compose logs --tail=100 kova-worker
   ```
2. If running manually, check Celery connection:
   ```bash
   celery -A app.workers.celery_app status
   ```

### Remedy
- Ensure `REDIS_URL` and `CELERY_BROKER_URL` are configured consistently between `kova-api` and `kova-worker`.
- For remote TLS-enabled Redis (`rediss://`), ensure the CA certificate and verification mode are configured in `backend/.env`:
  ```bash
  REDIS_SSL_CERT_REQS=required
  REDIS_SSL_CA_CERTS=kova-redis-ca.crt
  ```
- For local runs using `./start.sh`, inspect worker startup and runtime logs at `/tmp/worker.log`.
- Restart the worker:
  ```bash
  docker compose restart kova-worker
  ```

---

### Symptom: `Host system is missing dependencies! Target page, context or browser has been closed`

### Cause
Playwright Chromium is missing OS-level shared libraries on Linux (e.g., libnss3, libasound2, libxcomposite).

### Remedy
- In Docker, dependencies are bundled into the official image.
- In manual Linux installations:
  ```bash
  cd backend
  source .venv/bin/activate
  playwright install-deps chromium
  ```

---

### Symptom: Worker Killed Unexpectedly (`Exit Code 137` / OOM)

### Cause
Running multiple concurrent headless Chromium instances exceeded system memory. Each Chromium browser process requires approximately 1.0–1.5 GB of RAM.

### Remedy
- In `docker-compose.yml`, verify `kova-worker` memory limits:
  ```yaml
  deploy:
    resources:
      limits:
        memory: 3G
  ```
- Adjust worker concurrency from 2 down to 1:
  ```bash
  celery -A app.workers.celery_app worker --loglevel=info --concurrency=1
  ```

---

## 3. Database Connectivity & Migrations

### Symptom: `alembic.util.exc.CommandError: Can't locate revision identified by '...'` or Migration Failure

### Cause
The local database schema has stale or out-of-sync revision history.

### Remedy
1. Run migrations explicitly to view detailed traceback:
   ```bash
   cd backend
   source .venv/bin/activate
   alembic upgrade head
   ```
2. For fresh local testing, reset the database cleanly:
   ```bash
   docker compose down -v
   docker compose up -d
   ```

---

### Symptom: `asyncpg.exceptions.InvalidAuthorizationSpecificationError: password authentication failed`

### Cause
Credentials in `DATABASE_URL` do not match the PostgreSQL server credentials.

### Diagnostic & Remedy
- Verify `DATABASE_URL` format in `backend/.env`:
  `postgresql+asyncpg://<username>:<password>@<host>:<port>/<dbname>`
- Note that Kova uses AsyncSQLAlchemy with `asyncpg`. The dialect prefix must be `postgresql+asyncpg://`.

---

## 4. Frontend API Connection (`Network Error` / CORS)

### Symptom: Frontend Shows "Unable to reach API server" or CORS Errors

### Cause
`NEXT_PUBLIC_API_URL` is unset or points to an unreachable endpoint. Because `NEXT_PUBLIC_*` variables are inlined into the client-side JavaScript bundle during build time:

### Diagnostic
- Inspect network requests in the browser developer tools (F12) to see where the API requests are being directed.

### Remedy
1. In `frontend/.env.local`:
   ```ini
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```
2. When running via Docker Compose, rebuild the frontend container if `NEXT_PUBLIC_API_URL` is altered:
   ```bash
   docker compose up -d --build kova-frontend
   ```

---

## 5. Security & SSRF Blocks

### Symptom: `Blocked navigation to unsafe URL` or `SSRF: Aborting browser request`

### Cause
Kova's egress security firewall automatically detects and aborts navigation or subresource requests pointing to loopback (`127.0.0.1`), private RFC1918 subnets, or cloud metadata endpoints (`169.254.169.254`).

### Policy
This behavior is intentional to prevent server-side request forgery (SSRF). When testing against local services, test against public URLs or use designated non-reserved test domains.
