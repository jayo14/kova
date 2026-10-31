# Kova Architecture

## Runtime Topology

```
frontend (Next.js) --HTTP/WS--> kova-api (FastAPI)
kova-api --Celery broker--> redis (db 1)
kova-api --events/frames--> redis (db 0)
kova-api --SQL--> postgres
kova-api --dispatch--> kova-worker (Celery, owns Chromium/Playwright)
```

- **kova-api**: REST + SSE + WebSocket gateway. Never launches browsers.
- **kova-worker**: Celery worker; owns Chromium. Each run = one isolated browser context + profile, deleted afterward unless persistence explicitly requested.
- **redis**: broker (db 1) + ephemeral frames/state (db 0).
- **postgres**: durable data (flows, executions, evidence, product graph).

## State Machine (Execution Control)

Execution control is authoritative in `engine/execution/control.py`:

`RUNNING -> PAUSE_REQUESTED -> PAUSED -> RESUME_REQUESTED -> RUNNING`
`RUNNING/PAUSED -> QUIESCING -> HUMAN_CONTROL -> RECONCILING -> RUNNING`

- Human takeover reserves a lease; the agent quiesces at a safe boundary and reports outcome (idle/known/uncertain).
- Reconciliation re-observes the live page before resuming; interrupted actions with unknown effects are flagged `pre_resume_uncertain`.
- Terminal states (COMPLETED/FAILED/ERROR/CANCELLED/TIMEOUT) reject further control changes.

## AI Proposes, Code Disposes

- AI (reasoner/agent) proposes targets, actions, and plans as typed schemas (`engine/ai/schemas.py`).
- Validator (`engine/ai/validator.py`) converts semantic targets to deterministic selectors and rejects unsafe proposals.
- Egress guard (`engine/browser/egress.py`) resolves DNS once, pins IPs, blocks private/loopback/link-local/metadata at the network layer.
- Only deterministic verification (verifier) can mark a run complete; AI output never grants success.

## Browser Isolation

- Non-root worker, read-only root fs, tmpfs for profiles, cap_drop ALL, no-new-privileges, CPU/memory limits.
- Fresh context+profile per job; deleted after unless persistence requested.
- Permissions denied by default (camera, mic, geo, notifications, clipboard, arbitrary downloads).
- Downloads are job-scoped with type/size limits.

## Validation Modes

Per-flow `ValidationMode`: functional, workflow, regression, exploratory, visual. Each has distinct `SuccessCriteria` in `validation/success_criteria.py`. `ValidationScope` (targeted/expanded/full) is orthogonal and applies to regression breadth.
