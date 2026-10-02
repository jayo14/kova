# Kova Realtime Execution Events — Backend SSE Contract Specification

This document defines the required Server-Sent Events (SSE) contract for streaming execution updates from the FastAPI backend to the Next.js frontend.

---

## 1. Overview

Kova executions run asynchronously in background workers (Celery + Playwright). The browser requires a unidirectional stream of execution events to reflect progress, actions, observations, and verification in realtime without manual page reloads or wasteful polling loops.

```text
FastAPI (/executions/{id}/events/stream)
   │
   ▼ (Server-Sent Events)
Next.js Frontend (lib/realtime/executions.ts)
   │
   ▼ (React Hook: useExecutionRealtime)
Execution UI (Activity Timeline + Status Badge)
```

---

## 2. Endpoint Specification

- **Path**: `GET /api/v1/executions/{execution_id}/events/stream`
- **Protocol**: HTTP/1.1 or HTTP/2 Server-Sent Events
- **Response Headers**:
  ```http
  Content-Type: text/event-stream
  Cache-Control: no-cache, no-transform
  Connection: keep-alive
  X-Accel-Buffering: no
  ```

---

## 3. Authentication & Security

Native browser `EventSource` cannot send custom `Authorization: Bearer <token>` headers. To prevent leaking long-lived access tokens into URLs, query parameters, proxy logs, or browser histories:

### Preferred Option A: Same-Origin Cookie Authentication
- Frontend issues request with `withCredentials: true`.
- Backend validates HTTP-only session cookie (`sb-access-token` or custom session cookie).

### Preferred Option B: Short-Lived Stream Ticket
- Frontend requests a single-use, short-lived (e.g., 30–60 second) ticket:
  ```http
  POST /api/v1/executions/{execution_id}/stream-ticket
  Authorization: Bearer <supabase_access_token>
  ```
  Response:
  ```json
  {
    "ticket": "st_9b1deb4d3b7d4b89",
    "expires_in": 30
  }
  ```
- Browser connects using:
  ```
  GET /api/v1/executions/{execution_id}/events/stream?ticket=st_9b1deb4d3b7d4b89
  ```
- Backend consumes the ticket once and verifies it belongs to the authenticated user and execution.

### Explicit Security Rule
- **NEVER** accept or allow long-lived Supabase JWTs in the query string (`?token=eyJ...`).

---

## 4. SSE Message Format

Each message MUST follow the standard SSE text format:

```text
id: 018f4a12-8d9e-7c34-b26a-9213f56b0001
event: action.completed
data: {"id":"018f4a12-8d9e-7c34-b26a-9213f56b0001","execution_id":"a84f3c7e-...","event_type":"action.completed","payload":{"action":"click","target":"Sign In Button"},"created_at":"2026-09-16T10:00:00.000Z"}

```

### Heartbeat
To keep intermediaries and proxies from closing idle connections during pauses between agent actions:
```text
: ping

```
(Sent every 15 seconds if no events occur).

---

## 5. Event Types (`event_type`)

Matching `backend/app/modules/executions/event_types.py`:

| Event Type | Description | Terminal? |
|---|---|---|
| `execution.created` | Execution record created | No |
| `execution.queued` | Worker has enqueued execution | No |
| `execution.started` | Worker has started Playwright session | No |
| `browser.started` | Browser instance initialized and ready | No |
| `page.loaded` | Target page navigation finished | No |
| `agent.observed` | Agent mapped actionable page elements | No |
| `action.started` | Action initiated (click, type, navigate) | No |
| `action.completed` | Action executed successfully | No |
| `verification.started` | Verification assertion started | No |
| `verification.passed` | Verification assertion passed | No |
| `verification.failed` | Verification assertion failed | No |
| `recovery.started` | Autonomous recovery path started | No |
| `execution.completed` | Mission completed and verified | **Yes** |
| `execution.failed` | Mission failed or encountered unrecoverable error | **Yes** |
| `execution.cancelled` | Mission stopped by user request | **Yes** |
| `execution.timeout` | Mission exceeded time budget | **Yes** |

---

## 6. Stream Termination & Completed Executions

1. **Terminal State**:
   When the worker finishes or execution is cancelled, emit the terminal event (`execution.completed`, `execution.failed`, `execution.cancelled`, or `execution.timeout`), followed by an end-of-stream event:
   ```text
   event: done
   data: {}

   ```
   The backend then cleanly closes the HTTP connection.

2. **Already-Completed Execution**:
   If a client connects to an execution that is ALREADY in a terminal state, the backend MUST:
   - Emit existing events (or the final state event).
   - Emit `event: done`.
   - Close the connection immediately without hanging.

---

## 7. Reconnection & Resumption (`Last-Event-ID`)

- When a connection drops, the browser sends the `Last-Event-ID` header with the last received event ID.
- The backend queries `ExecutionEvent` where `execution_id = :id AND id > :last_id ORDER BY created_at ASC` and streams only missed events before resuming live broadcasting.
