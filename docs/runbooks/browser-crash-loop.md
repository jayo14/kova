# Runbook: Browser Crash Loop

## 1. Symptom & Alert
- **Alert:** `KovaBrowserCrashSpike`
- **Condition:** `rate(browser_crashes_total[5m]) > 0.5` (multiple browser crashes per second).
- **Impact:** Flow executions immediately fail with `TargetClosedError` or `BrowserError`; worker processes exhaust resources repeatedly restarting Chromium instances.

## 2. Diagnosis
Run on worker host or view centralized logging:

```bash
# 1. Query metrics to pinpoint which organization is triggering the crash spikes
curl -s http://localhost:8000/metrics | grep "browser_crashes_total"

# 2. Check recent failed executions in database
psql $DATABASE_URL -c "
SELECT e.id, e.flow_id, p.name as project_name, p.org_id, e.error_message, e.created_at
FROM executions e
JOIN flows f ON e.flow_id = f.id
JOIN projects p ON f.project_id = p.id
WHERE e.status = 'FAILED' AND e.created_at > NOW() - INTERVAL '30 minutes'
ORDER BY e.created_at DESC
LIMIT 10;
"

# 3. Check system resource exhaustion (OOM or shared memory /dev/shm exhaustion)
df -h /dev/shm
free -m
dmesg -T | grep -E -i "chromium|playwright|oom"
```

Common root causes:
- An organization's target app under test contains heavy WebGL, massive memory leaks, or malicious JS causing Chromium renderer crashes.
- `/dev/shm` shared memory exhaustion on Linux Docker / worker container (Chromium requires `--disable-dev-shm-usage` or large `/dev/shm`).
- Playwright Chromium version mismatch or missing OS font/graphics dependencies (`libx11-xcb`, `libasound2`, etc.).

## 3. Immediate Mitigation
1. **Temporarily quarantine or disable the offending organization's executions:**
   ```sql
   -- Set max_concurrent_executions to 0 to pause org's queue
   UPDATE organization_quotas 
   SET max_concurrent_executions = 0 
   WHERE org_id = '<offending_org_id>';
   ```
2. **Clean up zombie browser processes on worker nodes:**
   ```bash
   pkill -9 -f chromium
   pkill -9 -f playwright
   ```
3. **If `/dev/shm` is full:**
   Ensure Chromium launch arguments in `BrowserSession` include `--disable-dev-shm-usage` and `--no-sandbox`.

## 4. Root-Cause Investigation
- Pull execution trace or DOM state prior to crash from `evidence_events`.
- Inspect URL of target application:
  `SELECT target_url FROM flows WHERE id = '<flow_id>';`
- Run isolated single flow execution in dev container with headful browser or extra logging:
  `HEADLESS=false python -m app.engine.execution.runner ...`

## 5. Prevention
- Enforce strict per-page memory limits and navigation timeouts in Playwright.
- Allocate at least 2GB of `/dev/shm` to worker containers.
- Isolate execution sandboxes with container limits (cgroups cpu/memory caps).
