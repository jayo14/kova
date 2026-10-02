# Kova Milestone 1 — Forensic Architecture & Reliability Audit Report

**Date:** September 17, 2026  
**Auditor:** Antigravity Engine (Milestone 1 Forensic Inspector)  
**System:** Kova Autonomous Browser Execution Engine  
**Milestone Scope:** Milestone 1 (Deterministic Execution, Zero LLM / Zero AI Providers)  
**Target Repository:** `/home/codegallantx/moi/kova`

---

## 1. Executive Summary

Kova is architected as an agentic browser execution platform intended to explore target web applications, discover interaction surfaces and workflows, synthesize structured missions, execute browser actions autonomously via Playwright, verify mission success via deterministic DOM state rules, and record execution evidence (events, screenshots, network telemetry).

Milestone 1 was specified to be **100% deterministic**: no LLM dependencies, no fuzzy heuristics, and no ungrounded generative behavior.

### High-Level Verdict: **CRITICALLY BROKEN & FUNCTIONALLY DECOUPLED**

While individual backend units (such as database repositories and isolated resolver utilities) pass unit tests, **the end-to-end user journey is completely non-functional**. Specifically:

1. **The Explore Flow Frequently Gets Stuck on the Explore Screen:**
   - **Authentication Deadlock:** When a site prompts for authentication, the backend transitions to `AUTH_REQUIRED` and terminates its worker thread, but `AUTH_REQUIRED` is omitted from the SSE endpoint's `terminal_statuses`. The SSE generator hangs in a perpetual polling loop. When the user enters credentials, the frontend `submitCredential` awaits the SSE stream, which never closes. The submit button spins infinitely with `Signing in...` while the UI is frozen.
   - **Context Dissociation on Credential Submission:** When `submit_credentials` is called, the backend instantiates a brand new `ExplorationEngine` with a brand new `BrowserSession`, discarding the cookies, session history, and current DOM state of the existing session.
   - **Zero-State Deadlock:** If discovery produces fewer than 2 interactive elements matching hardcoded heuristics (e.g. on non-quiz web applications), the engine returns `missions: []` and status `READY`. The frontend conditional renderer `{state.state === "ready" && state.missions.length > 0}` fails to render any candidate missions while keeping the split viewport open with `AgentStatus` displaying "Ready", leaving the user stranded with zero actionable controls.
   - **Local URL Target Rejection:** The input parser's regex strictly requires a top-level domain (`\.[a-zA-Z]{2,}`). Local testing targets such as `http://localhost:3000`, `localhost:8000`, or `http://127.0.0.1:3000` are categorized as free-text goals with `url: null`. The dashboard redirects to `/explore?intent=localhost:3000`, where the explore page initializes with `initialUrl: ""`, remaining perpetually stuck on the idle hero screen.

2. **The "Agent Browser Viewport" is a Dangerous Security Illusion:**
   - The frontend component `AgentBrowserViewport` does **not** stream Playwright browser state. Instead, it renders a native client-side `<iframe src={targetUrl}>`.
   - Any website with standard security headers (`X-Frame-Options: DENY` or `Content-Security-Policy: frame-ancestors 'none'`) immediately crashes with a browser frame rejection error.
   - The frontend attempts cross-origin DOM password injection directly into `iframe.contentDocument`, which is blocked by the browser's Same-Origin Policy (SOP).
   - In the execution screen (`execution-browser.tsx`), the viewport is completely mocked: it renders a static CSS spinner stating "Operating the browser autonomously. The live browser stream will appear here."

3. **Step Schema Incompatibility Between Discovery & Execution:**
   - Discovered candidate missions synthesize `steps` as unstructured human-readable strings (e.g. `["Navigate to generator", "Select input", "Generate quiz"]`).
   - The execution engine `FlowRunner._normalize_step` converts these strings into action dictionaries without a target (`target: {}`).
   - The browser action validator `backend/app/engine/browser/actions.py` strictly mandates: `if target.is_empty(): errors.append("'click' requires a target")`.
   - **Result:** Every synthesized mission immediately fails validation on Step 1 with `ActionValidationError: 'click' requires a target` and terminates as `FAILED` after 3 retries.

4. **Hardcoded Domain Heuristics Disguised as Autonomous Exploration:**
   - The exploration engine (`explorer.py`) contains hardcoded string filters tailored exclusively to a single prototype quiz application (`["quiz", "material", "score", "profile"]`). On any general SaaS or web tool, discovery returns empty candidate sets.

---

## 2. Architecture Map

```
+----------------------------------------------------------------------------------------------------+
|                                         FRONTEND (Next.js 14)                                      |
|                                                                                                    |
|  [CommandInput] -------> [ExplorePage] ------------------------> [ExecutionDetailPage]            |
|        |                       |                                              |                    |
|  input-parser.ts        explore-state-machine.ts                      useExecutionRealtime.ts      |
|  (Regex TLD parse)             |                                              |                    |
|                        +-------+-------+                                      |                    |
|                        |               |                                      |                    |
|                        v               v                                      v                    |
|               AgentBrowserViewport   SSE Client (streamExplorationEvents)  EventMapper             |
|               (Direct client iframe)           |                              |                    |
+------------------------------------------------|------------------------------|--------------------+
                                                 | HTTP / SSE                   | HTTP / SSE
                                                 v                              v
+----------------------------------------------------------------------------------------------------+
|                                         BACKEND (FastAPI)                                          |
|                                                                                                    |
|  [Routes: /api/v1/exploration]                       [Routes: /api/v1/executions]                  |
|          |                                                         |                               |
|  ExplorationService                                          ExecutionService                      |
|          |                                                         |                               |
|          |-- ThreadPoolExecutor (Background)                       |-- Celery Task Dispatcher      |
|          v                                                         v                               |
|  ExplorationEngine                                           Celery Worker: execute_flow           |
|  (Playwright BrowserSession)                                       |                               |
|          |                                                   FlowRunner                            |
|          |                                                         |                               |
|          |                                                   BrowserSession / ActionExecutor       |
|          v                                                         v                               |
|  Redis Pub/Sub (Exploration Events)                          Redis Pub/Sub / DB Event Store        |
+----------------------------------------------------------------------------------------------------+
                                                 |
                       +-------------------------+-------------------------+
                       |                                                   |
                       v                                                   v
+-----------------------------------------------+   +-----------------------------------------------+
|             POSTGRESQL / SUPABASE             |   |                 REDIS (KeyDB)                 |
|                                               |   |                                               |
|  - projects, flows, flow_steps                |   |  - Celery task broker (db 0)                  |
|  - executions, execution_steps                |   |  - Exploration event pub/sub                  |
|  - execution_events, verification_results     |   |  - Execution event pub/sub                    |
+-----------------------------------------------+   +-----------------------------------------------+
```

### Component Breakdown & Role Analysis

| Layer | Component | Path | Stated Purpose | Actual Behavior |
|---|---|---|---|---|
| **Frontend** | `input-parser.ts` | `frontend/lib/agent/input-parser.ts` | Parse user input into URL, goal, and type | Fails on `localhost`, IP addresses, or non-dot inputs. Treats them as goals with `url: null`. |
| **Frontend** | `explore-page.tsx` | `frontend/components/explore/explore-page.tsx` | Exploration coordinator and mission preview | Hangs when `missions: []` or during auth retry. Shows client iframe instead of remote browser. |
| **Frontend** | `agent-browser-viewport.tsx` | `frontend/components/agent/agent-browser-viewport.tsx` | Live agent browser preview | Embeds target URL in direct client iframe. Subject to SOP/X-Frame-Options blocking. |
| **Frontend** | `execution-browser.tsx` | `frontend/components/executions/execution-browser.tsx` | Execution agent viewport | Completely mocked. Shows a spinner and placeholder text. No images or live DOM. |
| **Backend** | `exploration.py` (Route) | `backend/app/api/routes/exploration.py` | SSE and exploration endpoints | SSE loop hangs indefinitely if status is `AUTH_REQUIRED`. |
| **Backend** | `service.py` (Exploration) | `backend/app/modules/exploration/service.py` | Exploration session orchestration | Re-creates browser sessions on credential submit, discarding page state. |
| **Backend** | `explorer.py` | `backend/app/engine/exploration/explorer.py` | Autonomous app discovery | Hardcoded quiz heuristics. Generates string steps that execution engine cannot parse. |
| **Backend** | `runner.py` | `backend/app/engine/execution/runner.py` | Step execution & verification loop | Fails string steps with empty targets (`'click' requires a target`). |
| **Backend** | `actions.py` | `backend/app/engine/browser/actions.py` | Action model validation | Strict target validation that rejects all synthesized discovery steps. |
| **Backend** | `evidence_storage.py`| `backend/app/engine/browser/evidence_storage.py`| Store screenshots in Supabase | Returns relative URL path instead of signed public/presigned HTTPS URL. |

---

## 3. Actual Runtime Flow vs. Expected Runtime Flow

### Expected Deterministic Runtime Flow (Milestone 1 Spec)
1. **Target Input:** User submits URL (`https://quiza.app` or `http://localhost:3000`) and goal (`"Test user login and quiz flow"`).
2. **Session Initialization:** Backend spawns headless Chromium via Playwright, navigates to target URL, injects observer script, and records initial screenshot.
3. **Exploration & Discovery:**
   - Engine inspects DOM tree deterministically: forms, buttons, links, inputs.
   - Classifies page state: Auth required, Dashboard, Form, or Content.
   - If Auth required: Emits `AUTH_REQUIRED` with detected fields (`username`, `password`), suspends session, and preserves browser context.
   - If Ready: Extracts semantic workflows and emits structured candidate missions with valid Playwright selector steps.
4. **Mission Selection:** User selects discovered mission on frontend.
5. **Compilation to Flow:** Mission compiles into a database `Flow` with concrete `FlowStep` records containing actionable selectors (`id`, `css`, `xpath`, `text`).
6. **Execution via Celery Worker:**
   - Worker launches Playwright session.
   - Resolves target selector with deterministic fallback priority (ID -> TestID -> Name -> Aria -> CSS -> Text).
   - Executes action with pre-action and post-action DOM stability checks.
   - Captures evidence screenshot, hashes DOM state, checks deterministic verifier assertions.
   - Streams live progress events and screenshot URLs via SSE/Redis to frontend.
7. **Terminal Verification:** Verifier evaluates exit criteria (URL match, DOM element presence, text match) and marks execution `COMPLETED` or `FAILED`.

---

### Actual Runtime Flow (What Really Happens)

```
[User inputs URL: "localhost:3000"]
         |
         v
[input-parser.ts] ---> Regex fails ('localhost:3000' has no TLD). Returns url: null, goal: "localhost:3000"
         |
         v
[Redirect to /explore?intent=localhost:3000] (URL param omitted!)
         |
         v
[ExplorePage] sees initialUrl === "". Stays in IDLE state. NOTHING HAPPENS.
------------------------------------------------------------------------------------------------------
[User inputs URL: "https://example.com"]
         |
         v
[input-parser.ts] passes. Redirects to /explore?url=https://example.com
         |
         v
[ExplorePage] mounts. Starts SSE via streamExplorationEvents().
         |
         v
[Backend] spawns Playwright in background ThreadPool. Navigates to target.
         |
    +----+---------------------------------------------------------------+
    |                                                                    |
    v                                                                    v
[Scenario A: Login Required]                          [Scenario B: General Website (Not a Quiz)]
    |                                                                    |
    v                                                                    v
Engine detects password input.                        Engine runs _discover_workflows().
Status -> AUTH_REQUIRED.                              Filter checks for "quiz", "material", "score".
Background thread exits.                              No matches found. discoveries = [], missions = []
    |                                                 Status -> READY.
    v                                                                    |
Backend SSE stream DOES NOT close                                        v
(AUTH_REQUIRED not in terminal_statuses).             Frontend receives status: "READY", missions: []
    |                                                                    |
    v                                                                    v
User fills credential form on UI.                     Frontend conditional check:
Frontend calls submitCredential().                    {state.state === "ready" && state.missions.length > 0}
Frontend awaits streamExplorationEvents().            FAILS TO RENDER!
    |                                                 Split browser is locked.
    v                                                 AgentStatus displays "Ready".
Login fails or redirects.                             NO BUTTONS. NO MISSIONS. UI STUCK FOREVER.
Status remains non-terminal.
SSE never yields "done".
UI Submit button spins infinitely.
STUCK ON EXPLORE SCREEN.
------------------------------------------------------------------------------------------------------
[Scenario C: Hardcoded Quiz App Discovered]
    |
    v
Engine emits candidate mission with steps: ["Navigate to generator", "Select input", "Generate quiz"]
    |
    v
User clicks "Select Mission" -> Backend creates Flow & FlowSteps.
FlowSteps created with action="click", target={}.
    |
    v
Celery worker picks up execution.
FlowRunner._normalize_step parses step.
action_validator runs: "if target.is_empty(): errors.append(\"'click' requires a target\")"
    |
    v
EXECUTION FAILS IMMEDIATELY ON STEP 1 WITH ActionValidationError.
```

---

## 4. Exact Explore-Stuck Failure Analysis

The primary operational bug reported by users is: **The system gets stuck on the Explore screen.**

Through deep code tracing, four distinct, compounding failure mechanisms were identified that cause this exact symptom:

### Failure Mechanism 1: The Authentication SSE Stream Deadlock
- **Files:**  
  `backend/app/api/routes/exploration.py` (lines 80–118)  
  `backend/app/modules/exploration/service.py` (lines 142–158)  
  `frontend/lib/api/exploration.ts` (lines 53–78)  
  `frontend/components/explore/explore-page.tsx` (lines 160–185)
- **Trace:**
  1. Target page has a login form. Backend `_detect_auth_requirement` sets `status = ExplorationStatus.AUTH_REQUIRED`.
  2. The background thread `_execute_exploration_flow` returns immediately on line 157 of `service.py`:
     ```python
     if auth_required:
         self._update_session(session_id, status=ExplorationStatus.AUTH_REQUIRED, ...)
         return  # Thread exits!
     ```
  3. In `routes/exploration.py`, the SSE generator `stream_exploration_events` defines terminal states:
     ```python
     terminal_statuses = {
         ExplorationStatus.READY,
         ExplorationStatus.COMPLETED,
         ExplorationStatus.FAILED,
         ExplorationStatus.CANCELLED,
     }
     ```
     Notice that `ExplorationStatus.AUTH_REQUIRED` is **not** in `terminal_statuses`.
  4. The SSE generator continues polling Redis/DB indefinitely.
  5. On the frontend, `submitCredential` in `frontend/lib/api/exploration.ts` executes:
     ```typescript
     await streamExplorationEvents(sessionId, (event) => { ... });
     ```
  6. Because `AUTH_REQUIRED` never closes the SSE stream, `await streamExplorationEvents` **never resolves**.
  7. In `ExplorePage`:
     ```typescript
     const handleCredentialSubmit = async (creds) => {
       setCredentialLoading(true);
       try {
         await submitCredential(sessionId, creds);
       } finally {
         setCredentialLoading(false); // NEVER REACHED
       }
     };
     ```
  8. The user clicks "Submit Credentials", the button changes to "Signing in...", and the entire page hangs permanently.

### Failure Mechanism 2: Context Destruction on Credential Submission
- **Files:**  
  `backend/app/modules/exploration/service.py` (lines 160–190)
- **Trace:**
  1. When credentials are submitted via `/api/v1/exploration/{session_id}/credentials`, `ExplorationService.submit_credentials` runs:
     ```python
     session = self._active_browser_sessions.get(session_id)
     # ...
     engine = ExplorationEngine(url=session.url)
     future = self._executor.submit(self._execute_exploration_flow, session_id, engine, credentials)
     ```
  2. `ExplorationEngine` initializes a **brand new** `BrowserSession`, launching a fresh Chromium instance navigating to `session.url`.
  3. Any pre-existing session state (cookies, redirected auth URLs, CSRF tokens, session storage, dynamic challenge state) captured in the initial browser is wiped out.
  4. The new browser loads the initial URL, hits the login wall again, detects auth requirement again, and enters a recursive deadlock.

### Failure Mechanism 3: The Empty Missions Zero-State Dead End
- **Files:**  
  `backend/app/engine/exploration/explorer.py` (lines 350–395)  
  `frontend/components/explore/explore-page.tsx` (lines 280–310)
- **Trace:**
  1. Target web page does not contain quiz-related keywords.
  2. In `explorer.py`, `_discover_workflows` filters elements:
     ```python
     interactive = [el for el in elements if el.get("is_interactive") and len(el.get("text", "").strip()) >= 3]
     if len(interactive) < 2:
         return {"discoveries": [], "missions": []}
     ```
  3. Discovery finishes with `status: READY`, `missions: []`.
  4. Backend publishes event `status: READY`. Frontend receives it and sets `state.state = "ready"`, `state.missions = []`.
  5. In `ExplorePage.tsx`:
     ```tsx
     {state.state === "ready" && state.missions.length > 0 && (
       <div className="space-y-4">...Mission Cards...</div>
     )}
     ```
  6. Because `state.missions.length === 0`, **nothing is rendered in the control panel**.
  7. However, `showSplitBrowser` is still `true`. The right-hand pane shows the blocked iframe, the left-hand pane shows `AgentStatus` stating "Ready" with a green dot, but the rest of the screen is blank. There are no missions to select, no error messages, and no restart buttons. The user is stranded.

### Failure Mechanism 4: Strict URL Regex Blocking Localhost & IPs
- **Files:**  
  `frontend/lib/agent/input-parser.ts` (lines 14–22)  
  `frontend/components/dashboard/command-input.tsx` (lines 62–74)
- **Trace:**
  1. Developer or user tests locally with `http://localhost:3000` or `localhost:8080`.
  2. `input-parser.ts` runs:
     ```typescript
     const looksLikeUrl = (str: string): boolean => {
       if (str.startsWith("http://") || str.startsWith("https://")) return true;
       return /^[a-zA-Z0-9][-a-zA-Z0-9]*(\.[a-zA-Z0-9][-a-zA-Z0-9]*)*\.[a-zA-Z]{2,}(:\d+)?(\/.*)?$/.test(str);
     };
     ```
     If the user types `localhost:3000` (without `http://`), the regex fails because `localhost` does not have a 2+ letter TLD (`\.[a-zA-Z]{2,}`).
  3. `parseUserInput("localhost:3000")` returns:
     ```json
     { "url": null, "goal": "localhost:3000", "type": "navigate" }
     ```
  4. In `CommandInput`:
     ```typescript
     const params = new URLSearchParams();
     if (intent.url) params.set("url", intent.url);
     params.set("intent", intent.goal);
     router.push(`/explore?${params.toString()}`);
     ```
     The browser redirects to `/explore?intent=localhost%3A3000` (parameter `url` is missing).
  5. In `ExplorePage`:
     ```typescript
     const initialUrl = searchParams.get("url") || "";
     // ...
     useEffect(() => {
       if (!initialUrl) return; // Returns immediately!
       startExploration(initialUrl);
     }, [initialUrl]);
     ```
  6. The explore page stays completely inert in the `idle` state.

---

## 5. Critical Bugs Inventory

### BUG-01: Exploration Step Schema Incompatible with Execution Validator
- **Location:** `backend/app/engine/exploration/explorer.py` (line 372) & `backend/app/engine/browser/actions.py` (lines 125–130)
- **Observed:** Discovered missions generate steps as raw English phrases (`["Navigate to form", "Click button"]`). When converted into database `FlowStep` records, they have `action="click"` and `target={}`.
- **Expected:** Steps produced by discovery must include valid target selectors (`{"css": "...", "xpath": "..."}`) compatible with `ActionTarget`.
- **Root Cause:** In `explorer.py`, candidate missions synthesize dummy string steps. In `actions.py`, `validate_action` asserts `if target.is_empty(): errors.append("'click' requires a target")`.
- **Runtime Impact:** 100% of discovered missions crash on step 1 of execution with an unhandled validation error.
- **Severity:** **P0 (Blocker)**
- **Fix:** Update discovery synthesis to emit fully qualified action definitions (`ActionTarget` with verified DOM selector, action enum, and deterministic input arguments).

---

### BUG-02: `AgentBrowserViewport` Iframe Security Violation & SOP Bypass
- **Location:** `frontend/components/agent/agent-browser-viewport.tsx` (lines 80–120)
- **Observed:**
  ```tsx
  <iframe
    ref={iframeRef}
    src={iframeSrc}
    sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
    className="w-full h-full border-0"
  />
  ```
- **Expected:** Viewport should display a rendered video stream, WebSocket screenshot canvas, or periodic screenshot frame from the remote Playwright sandbox.
- **Root Cause:** The frontend developer attempted to embed the target website directly in a browser iframe and access `iframe.contentDocument` to inject credentials and monitor navigation.
- **Runtime Impact:**
  - Standard websites send `X-Frame-Options: DENY` or CSP `frame-ancestors 'none'`, producing a blank gray iframe with browser console errors (`Refused to display ... in a frame because it set 'X-Frame-Options' to 'deny'`).
  - Accessing `iframe.contentDocument` throws `DOMException: Blocked a frame with origin "http://localhost:3000" from accessing a cross-origin frame`.
- **Severity:** **P0 (Architectural Defect)**
- **Fix:** Remove direct client iframe. Implement server-side screenshot capture in Playwright; stream base64 images or signed screenshot URLs via SSE/WebSocket into a responsive HTML5 Canvas or `<img>` viewer.

---

### BUG-03: Supabase Signed URL Generator Generates Invalid Relative URIs
- **Location:** `backend/app/engine/browser/evidence_storage.py` (lines 82–96)
- **Observed:** `create_signed_url` queries Supabase storage and extracts the `signedURL` attribute:
  ```python
  res = self.client.storage.from_(self.bucket).create_signed_url(path, expires_in)
  return res.get("signedURL")
  ```
  Supabase Python SDK returns a relative path: `/storage/v1/object/sign/evidence/execution_...`.
- **Expected:** Must return a fully qualified absolute URL: `https://<supabase-project>.supabase.co/storage/v1/object/sign/...`.
- **Root Cause:** Missing protocol and host resolution when parsing the storage response.
- **Runtime Impact:** Frontend attempts to fetch `http://localhost:3000/storage/v1/object/...`, resulting in immediate 404 Not Found on all screenshot evidence.
- **Severity:** **P1**
- **Fix:** Prefix the relative path with `f"{supabase_url}/storage/v1{signed_url}"` if not already an absolute URL.

---

### BUG-04: JWT Verification Algorithm Hardcoded to `ES256`
- **Location:** `backend/app/modules/auth/dependencies.py` (lines 45–60)
- **Observed:**
  ```python
  payload = jwt.decode(token, key, algorithms=["ES256"], audience="authenticated")
  ```
- **Expected:** Supabase auth tokens typically use `HS256` (symmetric HMAC using JWT secret) or `RS256` for JWKS asymmetric signing.
- **Root Cause:** Author hardcoded `ES256`, assuming an ECDSA key configuration.
- **Runtime Impact:** All valid Supabase access tokens are rejected with `InvalidAlgorithmError: The specified alg value is not allowed`. Users cannot authenticate to protected backend endpoints.
- **Severity:** **P0**
- **Fix:** Support `algorithms=["HS256", "RS256", "ES256"]` dynamically retrieved from environment settings.

---

### BUG-05: Missing Celery Task Serialization & Model Hydration
- **Location:** `backend/app/workers/tasks/executions.py` (lines 40–65)
- **Observed:** Celery task `execute_flow_task(flow_id, execution_id)` instantiates `FlowRunner` but passes raw UUID strings where ORM models or validated Pydantic schemas are expected by downstream methods.
- **Expected:** Clean retrieval and session management of SQLAlchemy models inside the worker context.
- **Root Cause:** SQLAlchemy models bound to the FastAPI request thread are detached or uninstantiated in the worker thread, causing `DetachedInstanceError`.
- **Runtime Impact:** Async execution crashes silently in Celery with task state `FAILURE`.
- **Severity:** **P1**
- **Fix:** Explicitly query models inside the worker with a dedicated `SessionLocal()` context manager and handle disconnection cleanly.

---

## 6. Mocked, Fake, and Simulated Implementations

A forensic scan across the repository was conducted to distinguish real deterministic code from simulated mocks:

| File | Component | Category | Analysis |
|---|---|---|---|
| `frontend/components/executions/execution-browser.tsx` | Execution Browser Stream | **PROD MOCK** | Completely fake. Renders a CSS spinner and static text: `"Operating the browser autonomously. The live browser stream will appear here."` No connection to backend screenshots, VNC, or SSE. |
| `backend/app/engine/exploration/explorer.py` (lines 350-390) | Discovery Workflow Extraction | **HARDCODED DEMO** | Hardcoded heuristics look specifically for keywords `"quiz"`, `"material"`, `"score"`, `"generator"`. Any non-quiz web application produces empty workflows. |
| `backend/app/engine/browser/session.py` (lines 210-235) | Network Idle Waiter | **FRAGILE SIMULATION** | Emulates network idle by sleeping `asyncio.sleep(0.5)`. This is not a real deterministic network quiescence listener (`waitForLoadState('networkidle')`). Causes race conditions on single-page apps. |
| `frontend/lib/realtime/executions.ts` (lines 80-110) | Execution Realtime Client | **STUB / DEAD CODE** | Implements fallback polling at 1000ms intervals, but drops errors silently and fails to re-subscribe if the initial SSE connection disconnects. |
| `backend/app/engine/verification/verifier.py` (lines 140-165) | Visual State Verification | **PARTIAL STUB** | Claims visual verification capability, but only performs basic DOM element presence and title checks. Visual perceptual diffing is completely uncalled. |

---

## 7. Browser Automation & Sandbox Architecture Problems

### 1. The Direct Iframe Illusion
The single greatest architectural flaw in the frontend is the assumption that the agent's browser session can be mirrored by putting the target URL in a Next.js `<iframe>`.
- **Why this fails:**
  - Modern web applications enforce Clickjacking protection:
    - `X-Frame-Options: SAMEORIGIN`
    - `Content-Security-Policy: frame-ancestors 'self'`
  - Cookies and authentication are isolated to the user's browser instance, not the backend Playwright container. If the user logs in via the iframe, the backend Playwright browser knows nothing about it. If the backend logs in, the iframe remains unauthenticated.
  - The frontend navigation buttons (`back`, `forward`, `reload`) manipulate `iframe.contentWindow.history`, having zero link to the backend Playwright page instance.

### 2. Browser Sandbox Lifecycle & Leaks
In `backend/app/engine/browser/session.py`:
- Chromium is launched with:
  ```python
  self.browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
  ```
- If an exploration or execution task raises an unhandled exception or terminates unexpectedly, `session.close()` is frequently skipped because it is not enclosed in a robust `try ... finally` block across all call sites in `service.py` and `runner.py`.
- Zombie Chromium processes accumulate on the host OS, exhausting shared memory (`/dev/shm`) and causing subsequent Playwright launches to hang.

---

## 8. Authentication & Credential Security Analysis

### 1. Frontend Cross-Origin DOM Injection
In `frontend/components/agent/agent-browser-viewport.tsx`:
```typescript
const injectCredentials = (username, password) => {
  const doc = iframeRef.current?.contentDocument;
  if (!doc) return;
  const userInput = doc.querySelector('input[type="email"], input[type="text"]');
  const passInput = doc.querySelector('input[type="password"]');
  // ...
};
```
- **Security Vulnerability:** If the target website is hosted on the same origin (e.g. during local testing on port 3000), the frontend script directly reads and manipulates input fields without sanitation.
- **Architectural Failure:** For 99.9% of real-world websites, cross-origin restrictions completely block access to `contentDocument`, rendering this function completely dead.

### 2. Plaintext Credential Propagation
- Passwords entered in `ExplorePage` credential modal are sent over standard JSON payload to `/api/v1/exploration/{session_id}/credentials`.
- In `backend/app/modules/exploration/service.py`, credentials are stored unencrypted in memory dictionaries (`self._credentials[session_id] = credentials`).
- If an exception occurs, the credentials dictionary is logged in exception tracebacks in plaintext.

---

## 9. Verification & Evidence Storage Breakdown

### 1. Verification Logic Fragility
In `backend/app/engine/verification/verifier.py`:
- `DOMVerifier` evaluates mission success using three assertions:
  1. `url_equals` or `url_contains`
  2. `element_present` (CSS selector)
  3. `text_present` (String search)
- **Failure Mode:** In dynamic SPAs (React, Vue, Svelte), page transitions do not update the URL immediately. The verifier checks DOM state immediately after action execution without awaiting DOM stability or network idle. If an animation takes 200ms, the verifier reads the old DOM tree, flags the step as `VERIFICATION_FAILED`, and aborts the execution.

### 2. Evidence Storage Path Mismatch
- Screenshots are saved using `ScreenshotStorage` to bucket `screenshots`.
- Evidence results are queried using `EvidenceStorage` pointing to bucket `evidence`.
- The database `execution_steps.screenshot_url` stores the key in bucket `screenshots`, but the resolver in `routes/executions.py` attempts to generate signed URLs from the `evidence` bucket, returning `StorageKeyNotFoundError`.

---

## 10. Missing Deterministic Capabilities (Milestone 1 Scope)

Milestone 1 **does not need an LLM** to function reliably. Autonomous agents can be built with complete determinism using structured DOM analysis, accessibility trees, and rule-based state machines.

The following deterministic capabilities are currently missing and must be built:

1. **Accessibility Tree (AOM) Inspection:**
   - Instead of brittle regex searches for `"quiz"` in raw DOM strings, inspect the browser's Accessibility Tree (`page.accessibility.snapshot()`).
   - Identify roles (`button`, `textbox`, `link`, `checkbox`, `combobox`) and their accessible names.
   - Deterministically map all interactive targets on the screen without guessing.

2. **Deterministic Selector Fallback Hierarchy:**
   - Implement a rigid 6-tier selector resolver:
     1. `data-testid` / `data-test` / `data-qa`
     2. Semantic ID (`#login-submit`)
     3. Form Name attribute (`input[name="password"]`)
     4. Accessible Role & Name (`role=button[name="Submit"]`)
     5. Scoped CSS selector
     6. Stable XPath
   - Every synthesized discovery step must generate a full selector priority bundle rather than an empty target.

3. **Remote Screenshot Streaming (Eliminating the Iframe):**
   - After every navigation, click, or keystroke in Playwright, take a screenshot buffer (`page.screenshot(type="jpeg", quality=60)`).
   - Base64-encode or store in temporary memory, and push to the frontend SSE stream as a `SCREENSHOT_FRAME` event.
   - The frontend renders `<img src={currentFrameUrl} />` inside `AgentBrowserViewport`.
   - **Zero SOP errors, zero X-Frame-Options blocking, 100% faithful representation of the backend agent's environment.**

4. **Deterministic Network Quiescence Waiter:**
   - Replace arbitrary `sleep(0.5)` with Playwright's `waitForLoadState("networkidle")` and `waitForSelector(..., state="visible")`.

---

## 11. LLM Boundary Definition

To prevent scope creep and architectural contamination, the boundary between Milestone 1 (Deterministic Engine) and Milestone 2 (LLM Cognitive Layer) must be strictly enforced:

| Capability | Milestone 1: Deterministic Engine (Current) | Milestone 2: LLM Cognitive Layer (Future) |
|---|---|---|
| **Element Resolution** | Strict rule-based hierarchy (TestID -> ID -> Name -> Role -> Text). | Semantic similarity, visual grounding, fuzzy intent matching. |
| **Workflow Discovery** | Form discovery, link crawling, standard CRUD pattern detection via AOM. | Open-ended exploratory planning, unguided user goal interpretation. |
| **Mission Synthesis** | Standard templates: "Form Fill & Submit", "Search & Verify", "Navigation Flow". | Free-form natural language mission generation. |
| **Verification** | Exact DOM assertion (URL regex, element visibility, text equality). | Multi-modal visual verification, semantic success appraisal. |
| **Error Recovery** | Deterministic retries (exponential backoff, alternative selector in priority bundle). | Dynamic replanning, alternate workflow generation on obstacle. |

---

## 12. Priority Matrix & Actionable Fix Plan

| Priority | Issue ID | Component | Action Item |
|---|---|---|---|
| **P0** | BUG-01 | Exploration / Actions | Synthesize fully qualified `ActionTarget` objects with concrete selectors during discovery instead of empty targets. |
| **P0** | MECHANISM-1 | Backend Exploration | Include `AUTH_REQUIRED` in SSE `terminal_statuses` or implement dedicated auth SSE event emission. |
| **P0** | MECHANISM-2 | Backend Exploration | Reuse the existing `BrowserSession` in `_active_browser_sessions` when submitting credentials instead of spawning a new browser. |
| **P0** | BUG-02 | Frontend Viewport | Rip out client `<iframe>` in `AgentBrowserViewport`. Replace with image-based screenshot stream from Playwright. |
| **P0** | MECHANISM-4 | Frontend Parser | Update `input-parser.ts` to support `localhost`, local IP addresses (`127.0.0.1`), and explicit port numbers without TLD requirements. |
| **P0** | BUG-04 | Backend Auth | Update JWT verification in `dependencies.py` to allow `HS256` and `RS256` algorithms from Supabase. |
| **P1** | MECHANISM-3 | Explorer / Frontend | Implement generic DOM element clustering in `explorer.py` (remove hardcoded quiz heuristics). Add a clean empty-state UI in `ExplorePage` when no workflows are discovered. |
| **P1** | BUG-03 | Evidence Storage | Resolve Supabase relative URL strings into absolute signed HTTPS URLs in `evidence_storage.py`. |
| **P1** | BUG-05 | Celery Tasks | Ensure clean database session scoping and model serialization in `execute_flow_task`. |
| **P2** | SESSION-01 | Browser Session | Add deterministic `waitForLoadState('networkidle')` and ensure `try ... finally: session.close()` on all execution paths. |
| **P2** | VERIFY-01 | Verifier | Add explicit element visibility wait before running verifier assertions. |

---

## 13. Verification & Test Plan

To verify the remediation of Milestone 1 without modifying product requirements:

1. **Deterministic Test Suite Pass:**
   - Execute backend integration tests: `./venv/bin/pytest tests/integration/test_runner.py tests/integration/test_credentials.py tests/integration/test_executor.py`
   - All tests must pass with zero mock leaks.
2. **Localhost Target E2E Test:**
   - Spin up a local mock web application (e.g. a simple HTML form on `http://127.0.0.1:8085`).
   - Run input parser: verify `127.0.0.1:8085` correctly passes as `url`.
   - Initiate exploration: verify backend Playwright session navigates, captures screenshot, and streams base64 screenshot to frontend.
   - Verify discovery extracts form fields and outputs valid candidate missions with non-empty targets.
   - Click "Run Mission": verify Celery worker executes the click and fill actions without `ActionValidationError`.
   - Verify execution completes with state `COMPLETED` and valid screenshot evidence in the database.
3. **Auth Flow E2E Test:**
   - Target an authenticated local page: verify `AUTH_REQUIRED` stops the exploration stream cleanly.
   - Submit credentials: verify existing browser session receives keystrokes, submits form, verifies authenticated state, and transitions to `READY` without infinite spinner.
