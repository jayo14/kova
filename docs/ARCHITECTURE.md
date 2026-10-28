# Kova Architecture

## Runtime topology
- FastAPI API (`backend/app/main.py`) handles HTTP/WebSocket requests. Browser automation and long-running exploration/execution are not run in the API process for production paths.
- Celery workers (`backend/app/workers/`) own Playwright/Chromium for executions and exploration (isolated browser contexts per job).
- PostgreSQL for persistent state; Redis for control plane, pub/sub frames/state, and rate limiting.
- Frontend Next.js app communicates via REST + WebSocket to API.

## State machine (executions)
Execution flows through states defined in `backend/app/engine/execution/state.py`. Control state machine in `backend/app/engine/execution/control.py` supports RUNNING, PAUSE_REQUESTED, PAUSED, QUIESCING, HUMAN_CONTROL, RECONCILING, WAITING_FOR_USER, RESUME_REQUESTED, and terminals (COMPLETED, FAILED, CANCELLED, TIMEOUT, BLOCKED, UNVERIFIED). Only one controller may hold a lease at a time (expiring lease with heartbeat).

## AI-proposes, code-disposes boundaries
- Model outputs are parsed into Pydantic schemas and validated before any browser action (`backend/app/engine/ai/validator.py`). 
- The agent/executor/verifier are deterministic; the model can propose actions/plans but cannot mark an execution COMPLETED.
- Destructive actions require guard approval; tainted page content is sanitized; secrets are masked in logs/events.
- Success is proven by deterministic verification against pre-registered expectations; VLM/semantic checks are advisory only and cannot override failed/missing deterministic checks.
