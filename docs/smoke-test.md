# End-to-End Smoke Test Procedure

This document provides a genuine, reproducible procedure to verify that your local Kova installation is operational from the API layer down to the sandboxed browser execution worker.

---

## 1. Automated Smoke Test Suite

Kova includes a dedicated automated smoke test suite that verifies degradation modes, billing lifecycles, and security invariants in an isolated environment without external dependencies:

```bash
# Execute from the repository root:
./scripts/smoke/run_smoke.sh
```

### What this validates:
- **`test_ai_provider_degradation`**: Verifies that when upstream AI APIs fail or timeout, the engine degrades gracefully without crashing.
- **`test_s3_storage_degradation`**: Verifies fallback screenshot storage behavior when object storage is degraded.
- **`test_postgres_readiness_degradation`**: Confirms readiness retry behavior under transient DB latency.
- **`test_onboarding_journey`**: Verifies new user creation, project provisioning, and flow registration.
- **`test_security_invariants`**:
  - Rejects weak production JWT secrets.
  - Enforces that development mock users are disabled when `ENVIRONMENT=production`.
  - Proves that private subnets, loopback, and cloud metadata IPs (`169.254.169.254`) are blocked at the browser egress layer.
  - Asserts that sensitive headers and credentials are automatically redacted in audit trails.

Expected output:
```
=== Running Kova Production Launch Smoke Test Suite ===
...
============================= 11 passed in 17.02s ==============================
=== All production launch smoke tests passed successfully! ===
```

---

## 2. Interactive End-to-End Manual Smoke Test

Follow this test to verify the web UI and live browser worker execution:

### Step 1: Confirm Stack Health
Ensure all containers or background processes are running:
```bash
curl -fsS http://localhost:8000/health
```
Verify the response contains:
`{"status":"healthy","database":"connected","redis":"connected"}`

### Step 2: Open Dashboard & Create a Project
1. Open [http://localhost:3000](http://localhost:3000) in your browser.
2. Sign in with the local development credentials or create a new test organization.
3. Click **New Project** and enter a publicly accessible web application URL that you control (e.g. your staging site or personal blog).

### Step 3: Run Flow Exploration
1. Inside your project, click **Explore Application**.
2. Observe the real-time execution viewport in the dashboard:
   - Notice the status progress: `CONNECTING` → `LOADING` → `EXPLORING`.
   - The live browser view streams step-by-step frames over WebSocket (`ws://localhost:8000/api/v1/executions/{id}/stream`).
3. Verify that the Page Observer discovers interactive elements, navigation routes, and candidate missions.

### Step 4: Verify Evidence Artifacts
1. Once exploration completes, click into the execution details.
2. Inspect the audit trail:
   - Verify that step screenshots were captured and stored with sha256 checksums.
   - Verify that network requests are logged and sensitive cookies/authorization headers are marked `[REDACTED]`.
   - Confirm that the outcome status reflects an honest state (`COMPLETED` only if verified, or `BLOCKED` if an unresolvable login was encountered).
