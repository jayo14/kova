# Kova URL-Driven Agent Functionality Review

## Scope
I reviewed the repository implementation against landing-page/documentation claims that a user can provide a product URL and Kova will autonomously navigate and execute product journeys.

## Verdict
**Partially yes.**

Kova can autonomously start browser exploration from a submitted URL and navigate unsupervised through discovery steps.  
However, it does **not** currently provide fully hands-off “enter URL and it completes the journey” behavior end-to-end in all key paths.

## What Works Today

1. **URL input triggers autonomous exploration flow**
   - Landing hero sends the user to `/explore?url=...` (`/home/runner/work/kova/kova/frontend/components/marketing/hero.tsx:10-20`).
   - Explore page auto-starts exploration when `url` exists in query params (`/home/runner/work/kova/kova/frontend/components/explore/explore-page.tsx:132-172`).
   - Backend starts exploration session and launches background exploration task (`/home/runner/work/kova/kova/backend/app/api/routes/exploration.py:63-72`, `/home/runner/work/kova/kova/backend/app/modules/exploration/service.py:106-161`).

2. **Autonomous navigation/discovery is implemented**
   - Engine performs connect → load → validate → observe → discover workflow candidates (`/home/runner/work/kova/kova/backend/app/engine/exploration/explorer.py:234-552`).
   - SSE + polling updates stream to frontend (`/home/runner/work/kova/kova/frontend/lib/api/exploration.ts:497-599`).

3. **Execution engine exists**
   - Suggested missions can be converted to flows/executions and launched (`/home/runner/work/kova/kova/frontend/components/explore/explore-page.tsx:296-408`).
   - Backend execution pipeline is present via flow executions and worker dispatch (`/home/runner/work/kova/kova/backend/app/api/routes/flows.py:211-257`).

## Blockers / Hindrances for Full “URL → Autonomous Journey Completion” Promise

### 1) Manual mission confirmation is required before execution
- After exploration reaches READY, user must manually select/run missions in dialog.
- Evidence: mission dialog + explicit run action (`/home/runner/work/kova/kova/frontend/components/explore/explore-page.tsx:572-600`, `/home/runner/work/kova/kova/frontend/components/agent/mission-suggestions.tsx:59-64`).
- **Impact:** breaks fully unsupervised end-to-end expectation from a single URL input.

### 2) Exploration can stop for user intervention (credentials/role)
- Engine enters `AUTH_REQUIRED` if login is needed without credentials, and `ASKING` when multiple roles are detected.
- Evidence: auth barrier return (`/home/runner/work/kova/kova/backend/app/engine/exploration/explorer.py:389-417`), role question return (`:488-517`).
- **Impact:** autonomous run pauses frequently on real products unless credentials/role are pre-resolved.

### 3) URL intent is dropped for unauthenticated users entering via landing page
- Protected-route redirect keeps only pathname, not original query (`url`, `intent`).
- Evidence: middleware sets `redirect=pathname` only (`/home/runner/work/kova/kova/frontend/middleware.ts:53-60`).
- **Impact:** user enters URL on landing page, gets redirected to login, then loses initial target URL/intent context.

### 4) Exploration runtime durability is weak for production launch
- Exploration tasks/browsers are in API process memory (`_active_browser_sessions`, `_active_exploration_tasks`), not queue-worker durable.
- Evidence: in-memory maps/task spawning (`/home/runner/work/kova/kova/backend/app/modules/exploration/service.py:41-57`).
- Exploration hard timeout is only 120 seconds.
- Evidence: `EXPLORATION_TIMEOUT_SECONDS = 120` (`/home/runner/work/kova/kova/backend/app/modules/exploration/service.py:37-39`).
- **Impact:** restarts can kill active explorations; longer/complex product exploration can be cut off.

### 5) Setup/documentation mismatch can block quick launch readiness
- Root README says frontend setup uses `cp .env.example .env.local`, but frontend directory has no `.env.example`.
- Evidence: README setup instruction (`/home/runner/work/kova/kova/README.md:67-69`), frontend tree has no file (`/home/runner/work/kova/kova/frontend` listing).
- **Impact:** onboarding friction and failed first-run setup for teams/users.

### 6) Production URL safety policy blocks private/local targets
- URL safety rejects private/link-local/reserved ranges and localhost in production mode.
- Evidence: `_is_safe_url` and loopback policy (`/home/runner/work/kova/kova/backend/app/engine/browser/session.py:104-165`).
- **Impact:** users testing internal staging apps/private networks cannot run those targets without policy/config decisions.

## Launch-in-a-Week Risk Assessment
If launch expectation is **“enter URL and Kova autonomously completes the journey with minimal supervision”**, current state is **not fully launch-ready**.

Top launch-critical gaps to close before that promise is reliable:
1. Preserve URL/intent through auth redirect.
2. Decide and implement default auto-run behavior for recommended mission(s) after exploration.
3. Improve exploration runtime robustness (durable worker execution and/or longer timeout strategy).
4. Tighten onboarding docs/env setup consistency.

## Bottom Line
Kova already demonstrates substantial autonomous behavior, but the current product flow is still **semi-autonomous** (discovery-first, user-confirmed execution, and user-intervention checkpoints).  
For a one-week launch under the current public promise, these blockers are the main constraints.
