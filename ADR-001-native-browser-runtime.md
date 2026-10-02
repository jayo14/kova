# ADR-001: Native Browser Runtime & Live Control

## Status: Accepted

## Context

Kova's browser execution was previously a collection of iframes, static screenshots, decorative cursors, mocked takeover controls, disconnected WebSockets, and screenshots pretending to be a browser session. The product needed a real, native-ish browser experience where the viewport IS the execution's browser session.

## Decisions

### Decision 1: Chromium is owned by the browser runtime/worker, not FastAPI

The Celery worker owns Chromium, BrowserContext, and Page. FastAPI never directly manipulates a Playwright Page that belongs to another process. The WebSocket endpoint acts as a gateway, not a browser controller.

### Decision 2: Playwright Page is never shared across processes

Each execution gets its own isolated BrowserSession with its own Chromium instance. Playwright objects are never serialized, stored in Redis, or passed between processes.

### Decision 3: Live viewport frames are ephemeral and streamed through WebSocket

Live frames are binary JPEG screenshots broadcast via WebSocket at each execution sync point. They are NOT stored in PostgreSQL, NOT sent through SSE events, and NOT persisted to Supabase Storage (evidence is captured separately at verification/completion).

### Decision 4: Execution/control events remain on the structured event/SSE path

Execution lifecycle events (created, queued, running, completed, failed, paused, resumed) flow through PostgreSQL events and SSE. The WebSocket carries only browser data-plane traffic (frames, input, state).

### Decision 5: Persistent evidence is stored separately

Evidence screenshots are captured at verification, completion, and failure. They are stored in Supabase Storage and referenced by metadata in the event stream. Live frames and evidence are completely separate pipelines.

### Decision 6: iframe is not the canonical execution browser

LiveViewport renders actual Playwright frames received via WebSocket. The iframe remains only for non-executing exploration views. Execution viewing always uses the LiveViewport.

### Decision 7: Takeover is a real runtime state transition

Takeover flows through Redis pub/sub: WebSocket publishes "pause" command → runner checks at sync points → pauses execution → user interacts → publishes "resume" → runner re-observes and resumes. Not a UI flag.

### Decision 8: Browser session is authoritative over frontend representation

The Playwright page URL, title, and DOM state are the source of truth. The frontend toolbar displays what Playwright reports, not what the frontend computes.

### Decision 9: Journey discovery is deferred

Exploration improvements are deferred until browser execution is trustworthy. The current exploration engine remains functional but is not the focus of this milestone.

### Decision 10: Browser persistence/CDP reconnection/browser pooling are deferred

Each execution creates a fresh Chromium instance. Browser pooling, CDP persistence, and cross-worker browser migration are not implemented. Frontend WebSocket reconnect works (the browser continues running independently).

## Architecture

```
                         KOVA WEB APP
                              │
             ┌────────────────┴─────────────────┐
             │                                  │
          HTTP / SSE                        WebSocket
             │                                  │
             ▼                                  ▼
      ┌───────────────┐              ┌────────────────────┐
      │    FastAPI    │              │ Browser Gateway /  │
      │  Control API  │              │ Viewport Stream    │
      └───────┬───────┘              └─────────┬──────────┘
              │                                │
              └────────────┬───────────────────┘
                           │
                    Control / Events (Redis)
                           │
                           ▼
                 ┌─────────────────────┐
                 │  Browser Runtime     │
                 │  (Celery Worker)     │
                 │                     │
                 │ BrowserSession      │
                 │ FlowRunner          │
                 │ ActionExecutor      │
                 │                     │
                 │ Playwright          │
                 │ Chromium            │
                 └──────────┬──────────┘
                            │
                            ▼
                     TARGET WEBSITE
```

## Control Flow

### Agent → Browser
1. FlowRunner executes action via ActionExecutor
2. ActionExecutor calls Playwright Page methods
3. Browser captures screenshot → broadcast_frame() → WebSocket → LiveViewport canvas

### Human → Browser
1. User clicks "Take control" on LiveViewport
2. Frontend sends `takeover_accept` over WebSocket
3. WebSocket handler: `set_control_state("human")` → Redis
4. WebSocket handler: `publish_command("pause")` → Redis pub/sub
5. Runner: `check_pause()` → True → pause execution → broadcast "paused" state
6. User interacts → frontend sends input messages → WebSocket → `queue_user_input()` → Redis
7. Runner: `_process_user_input()` → Playwright Page methods
8. User clicks "Return control to Kova"
9. Frontend sends `return_control` → WebSocket → `set_control_state("agent")` → Redis
10. Runner: `wait_for_resume()` → True → re-observe → resume execution

### Browser → Frontend
1. Playwright page screenshot → JPEG bytes
2. `broadcast_frame()` → WebSocket binary frame
3. LiveViewport canvas renders frame
4. `broadcast_state()` → URL, title, control state updates
5. Frontend toolbar and overlays update

## Files Changed

### Backend (created)
- `backend/app/engine/execution/control.py` — Redis-based cross-process control channel

### Backend (modified)
- `backend/app/engine/execution/state.py` — Added PAUSED, HUMAN_CONTROLLED, RESUMING states
- `backend/app/engine/execution/context.py` — Added control_state field
- `backend/app/engine/execution/runner.py` — Continuous frame streaming, user input processing, pause/resume, UNVERIFIED handling
- `backend/app/engine/browser/session.py` — SSRF protection
- `backend/app/modules/executions/models.py` — Added PAUSED, HUMAN_CONTROLLED, RESUMING to DB enum
- `backend/app/modules/executions/state_machine.py` — Added transitions for new states
- `backend/app/modules/executions/event_types.py` — Added EXECUTION_PAUSED, EXECUTION_RESUMED, CONTROL_CHANGED
- `backend/app/workers/tasks/executions.py` — Handle new states in event recorder
- `backend/app/api/routes/viewport.py` — Redis control channel, WebSocket auth, ownership verification, cleaned up stubs

### Frontend (created)
- `frontend/components/agent/live-viewport.tsx` — Rebuilt with reconnection, input capture, takeover controls

### Frontend (modified)
- `frontend/components/executions/execution-browser.tsx` — Removed Site Frame iframe, LiveViewport as canonical browser
- `frontend/lib/types.ts` — Added paused, human_controlled, resuming states
- `frontend/lib/executions/status.ts` — Added new states to backend/frontend mapping
- `frontend/lib/utils/execution-status.ts` — Added badge styles for new states

## Known Limitations

- **Multiple tabs**: Single page only. New tabs from popups are not handled.
- **Browser pooling**: Each execution creates fresh Chromium. No reuse.
- **CDP persistence**: No persistent browser sessions across executions.
- **Browser crash recovery**: Browser failure surfaces as execution failure. No auto-restart.
- **Journey discovery**: Deferred. Exploration engine unchanged.
- **Video recording**: Not implemented. Live frames are ephemeral JPEGs.
- **Scaling**: Celery worker concurrency is the bottleneck. Each execution holds a worker.
- **Frame rate**: Dependent on screenshot capture speed (~1-5 FPS on modest hardware).
