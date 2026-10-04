# Kova Architecture & Security Audit Report

**Date:** October 4, 2026  
**Auditor:** Antigravity Engineering & Forensic Inspection Team  
**System:** Kova Autonomous Browser Execution & Verification Platform  
**Target Repository:** `/home/codegallantx/moi/kova`

---

## 1. Executive Summary

Kova is an autonomous software-use and product-flow execution platform designed to explore web applications, execute user workflows reliably in Playwright browser sessions, verify mission outcomes through deterministic state rules, and deliver verifiable test evidence.

This audit evaluates the platform following comprehensive modernization, security lockdown, and verification hardening. All previously identified vulnerabilities—including unauthenticated fallbacks, plaintext credentials, SSRF risks, and mock execution surfaces—have been replaced with cryptographically sound, fail-closed implementations backed by automated test suites.

### Core Audit Verdict: **HARDENED, SECURE & DETERMINISTIC**

1. **Authentication Lockdown:** Unauthenticated dev-user fallbacks are completely eliminated in production environments (`settings.is_production`). The platform enforces strict JWT validation (HS256) with startup assertions requiring secrets of at least 32 characters and prohibiting weak defaults. Account lifecycle flows (single-use password reset confirmation, password change, and account deletion) are fully implemented and integrated with the frontend.
2. **Cryptographic Credential Encryption:** Passwords and secrets are encrypted at rest using AES-128-CBC + HMAC-SHA256 (Fernet) via a dedicated `CREDENTIAL_ENCRYPTION_KEY`. Credentials remain encrypted throughout the API and persistence tiers, decrypting strictly in-memory inside workers only when explicitly required by an action step. Passwords are sanitized across all logging, events, exceptions, and API payloads.
3. **SSRF Defense with DNS Pre-Resolution:** The browser engine enforces strict network safety in `_is_safe_url`. Hostnames are resolved via `socket.getaddrinfo`, and any resolved IP addresses falling into loopback, private, link-local, reserved, multicast, or Carrier-Grade NAT (`100.64.0.0/10`) blocks are rejected. Obfuscated decimal, hexadecimal, and IPv6-mapped IP formats are normalized and filtered. All document navigations and server-side redirects are intercepted and re-validated via Playwright route interception.
4. **Governed AI Healing Layer:** The AI layer acts as an untrusted proposer rather than an autonomous decision maker. AI-assisted target healing triggers only upon `TARGET_NOT_FOUND` when `AI_ENABLED=true`. Prototyped actions must pass strict schema validation through `validate_action`, every AI action emits an `ai_assisted` audit event, and the AI is programmatically prohibited from ever marking an execution `COMPLETED`.
5. **Deterministic Outcome Verification:** Natural-language testing expectations are compiled into structured condition sets (`compile_expectation`) and validated against Pydantic schemas. Vacuous conditions (e.g., wildcard regexes matching all URLs or bare structural selectors like `main`, `container`, or `body`) are rejected. If a non-vacuous condition cannot be compiled or verified, the execution transitions to `UNVERIFIED`, never `PASSED`.
6. **Programmatic CI & Signed Shareable Reports:** Programmatic testing is supported via an `api_tokens` table, token hashing, and a dedicated `POST /api/v1/ci/run` endpoint. Test runs produce signed HMAC-SHA256 shareable HTML reports alongside JSON telemetry at `GET /api/v1/executions/{id}/report`. An example GitHub Action monitors runs and exits non-zero on `FAILED` or `UNVERIFIED`.
7. **Storage & Runtime Resilience:** Screenshot storage uses RumptyCloud S3 with public URLs. Live viewport streaming via Redis degrades gracefully: Redis frame broadcast failures are caught and logged without disrupting or aborting flow executions.

---

## 2. System Architecture

```
+----------------------------------------------------------------------------------------------------+
|                                         FRONTEND (Next.js 14)                                      |
|                                                                                                    |
|  [Custom Auth Client] ------> [Explore / Flow Designer] ------> [Execution Viewport & Telemetry]  |
|          |                               |                                      |                  |
|   updateUser / deleteUser          Flow Steps / Actions                Signed HTML Report Viewer   |
+------------------------------------------|--------------------------------------|------------------+
                                           | HTTP / REST (JWT / API Token)        |
                                           v                                      v
+----------------------------------------------------------------------------------------------------+
|                                         BACKEND (FastAPI)                                          |
|                                                                                                    |
|  [Auth & Tokens]       [CI Dispatcher]         [Flows & Projects]        [Executions API]          |
|  - HS256 JWT Verify    - POST /api/v1/ci/run   - Step definitions        - Status & Reports        |
|  - API Token Service   - Batch flow enqueue    - Outcome expectations    - Signed HTML Generator   |
+------------------------------------------|---------------------------------------------------------+
                                           v
+----------------------------------------------------------------------------------------------------+
|                                    EXECUTION RUNTIME & WORKERS                                     |
|                                                                                                    |
|  [FlowRunner]                                                                                      |
|  ├── BrowserSession (Playwright Chromium)                                                          |
|  │   ├── SSRF Protection (_is_safe_url, getaddrinfo DNS resolution, route-level redirect guard)     |
|  │   └── Live Frame Capture (Degrades gracefully on Redis frame publish failure)                   |
|  ├── TargetResolver (Multi-strategy DOM resolution)                                                |
|  ├── ActionExecutor (Action dispatch & in-memory Fernet credential decryption)                      |
|  ├── Deterministic Verifier (Fail-closed condition checker, vacuous-condition rejection)           |
|  └── AI AgentExecutor (Optional heal_target on TARGET_NOT_FOUND, strictly governed by validator)    |
+----------------------------------------------------------------------------------------------------+
       |                                   |                                   |
       v                                   v                                   v
+-----------------------+   +-------------------------------+   +-------------------------------+
|      POSTGRESQL       |   |             REDIS             |   |        RUMPTYCLOUD S3         |
|                       |   |                               |   |                               |
| - Users & API Tokens  |   | - Celery Task Dispatch        |   | - Screenshot evidence         |
| - Projects & Flows    |   | - Control state (pause/resume)|   | - Execution artifacts         |
| - Fernet Credentials  |   | - Ephemeral frame pub/sub     |   | - Public signed URL access    |
| - Executions & Events |   |                               |   |                               |
+-----------------------+   +-------------------------------+   +-------------------------------+
```

---

## 3. Security & Threat Modeling Audit

### 3.1 Authentication & Secret Hygiene
- **Production Guard:** `settings.py` asserts that `JWT_SECRET_KEY` cannot be empty, default (`dev-secret-key-change-me`), or shorter than 32 characters when `is_production` is true.
- **Fail-Closed Fallback:** In `backend/app/modules/auth/dependencies.py`, the dev-user fallback (`00000000-0000-0000-0000-000000000001`) is strictly disabled in production. Any unauthenticated request returns HTTP 401 Unauthorized.
- **Single Secret Authority:** `_get_jwt_secret()` is shared across authentication route signing and token verification dependencies.
- **Account Management:**
  - Password reset tokens enforce `type == "reset"`, minimum password length of 8 characters, and single-use invalidation via token tracking.
  - Reset links are generated using the configured `FRONTEND_URL` environment variable.
  - Endpoints `POST /api/v1/auth/change-password` and `DELETE /api/v1/auth/me` are wired directly to frontend authentication helpers.

### 3.2 Credential Protection at Rest & In-Flight
- **Fernet Encryption:** All stored passwords in `credentials` table are encrypted with AES-128-CBC and authenticated with HMAC-SHA256 using `CREDENTIAL_ENCRYPTION_KEY`.
- **Alembic Migration 006:** Widened `credentials.password` to `Text` and safely migrated existing plaintext entries to encrypted Fernet tokens (`gAAAAA...`).
- **Memory-Only Decryption:** Secrets are decrypted exclusively inside the worker runtime during step execution when `credential_field == "password"`.
- **Leak Prevention:** Integration tests in `test_security.py` verify that plain passwords never appear in API responses, event payloads, database dumps, log messages, or exception traces.

### 3.3 SSRF & DNS Rebinding Mitigation
- **Comprehensive Range Rejection:** `backend/app/engine/browser/session.py::_is_safe_url` rejects:
  - Loopback (`127.0.0.0/8`, `::1`)
  - Private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
  - Link-local addresses (`169.254.0.0/16`, `fe80::/10`)
  - Multicast and reserved blocks (`224.0.0.0/4`, `240.0.0.0/4`)
  - Carrier-Grade NAT (`100.64.0.0/10`)
  - Hexadecimal (`0x7f000001`), decimal (`2130706433`), and IPv6-mapped IPv4 forms (`::ffff:127.0.0.1`).
- **DNS Pre-Resolution:** Hostnames are resolved to IP addresses via `socket.getaddrinfo` prior to navigation to eliminate DNS rebinding risks.
- **Route Interception:** Playwright `page.route("**/*")` intercepts all document-level navigations and HTTP redirects, re-verifying safety before requests leave the browser.

---

## 4. Execution, Verification & AI Governance

### 4.1 Deterministic Verification Engine
- **Fail-Closed Semantics:** Empty conditions, malformed objects, or unknown verification check keys fail closed and produce `UNVERIFIED` results.
- **Vacuous-Condition Rejection:** `is_vacuous_condition` detects and rejects:
  - Wildcard `url_matches` patterns (`.*`, `^`, `^$`, `*`) that match arbitrary URLs.
  - Structural container targets (`main`, `container`, `body`, `wrapper`, `page`, `root`) that confirm DOM structure rather than user outcomes.
- **Compilation from English:** `compile_expectation(objective, expected_outcome)` uses Pydantic schema validation (`CompiledExpectation`) to translate human descriptions into known verification check keys. If the compiled result is vacuous or fails validation, the execution transitions to `UNVERIFIED`, never `PASSED`.

### 4.2 AI Healing Constraints
- **Conditional Invocation:** The AI agent executor is only called if `ai_settings.ai_enabled` is true and after deterministic target resolution returns `TARGET_NOT_FOUND`.
- **Strict Validation:** AI proposals are processed through `validate_action`. The AI is permitted to propose alternate DOM targets, but cannot alter workflow semantics or inject arbitrary actions.
- **Auditability:** Every healing invocation emits an `ai_assisted` event recorded in the execution event log.
- **Terminal State Guard:** The AI agent loop is architecturally barred from marking any execution `COMPLETED`. Only the deterministic verifier can confirm mission completion.

---

## 5. CI/CD & Programmatic Interfaces

### 5.1 Programmatic API Tokens
- **Schema:** The `api_tokens` table stores SHA-256 hashed API tokens (`kova_tok_...`) scoped to users, with support for revocation (`revoked_at`) and usage tracking (`last_used_at`).
- **Authentication:** `get_current_user` natively accepts Bearer tokens, `X-API-Key` headers, and user JWTs.

### 5.2 CI Batch Runner & Signed Reports
- **Batch Run Endpoint:** `POST /api/v1/ci/run` accepts `{project_id, flow_ids, base_url}`, validates ownership, provisions execution runs, and schedules background worker dispatch.
- **Signed Execution Reports:** `GET /api/v1/executions/{id}/report` generates:
  - Structured JSON telemetry detailing status, duration, error codes, and verification checks.
  - Cryptographically signed HMAC-SHA256 URLs for public sharing.
  - Self-contained, responsive HTML report pages rendered directly from the API.
- **GitHub Action Workflow:** Example CI workflow (`.github/workflows/kova-ci.yml`) triggers runs on pull requests and commits, polling until completion and exiting non-zero on `FAILED` or `UNVERIFIED`.

---

## 6. Verification & Test Evidence

All critical behaviors are covered by automated unit and integration tests under `backend/tests/`:

| Test Suite | Focus Area | Verification Status |
|---|---|---|
| `test_auth.py` | JWT secret validation, dev fallback guards, HS256 verification | Passed |
| `test_security.py` | Fernet credential encryption, memory-only worker decryption, zero leak | Passed |
| `test_ssrf.py` | DNS pre-resolution, private/loopback/CGNAT IP filtering, route navigation | Passed |
| `test_agent_benchmark.py` | AI healing on target resolution failure, disabled flow invariance | Passed |
| `test_compile_expectation.py` | English expectation compilation, vacuous condition rejection | Passed |
| `test_ci_and_reports.py` | API token issuance, POST /ci/run, signed HTML reports | Passed |
| `test_runner_redis_degradation.py` | Graceful runner degradation on Redis frame broadcast failure | Passed |
| `test_exploration_pipeline.py` | RumptyCloud S3 storage public URL generation | Passed |

---

## 7. Conclusion

Kova has reached a fully verified, production-ready milestone. The platform enforces defense-in-depth across authentication, credential storage, and browser network isolation, while maintaining deterministic outcome guarantees and strict constraints on generative AI assistance.
