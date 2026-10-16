# Operational Runbook: Production Launch Rollback

## Severity & Trigger
- **Severity**: P0 / Critical
- **Trigger**: Fatal application crash loops, widespread authentication failure, critical data corruption, or inability to process test executions post-deployment.
- **Target Recovery Time**: $\le 10$ minutes.

---

## Rollback Procedure

### 1. Identify Target Stable Commit
Find the last verified healthy release commit hash or container tag:
```bash
git log -n 5 --oneline
# Example target: PREV_STABLE_COMMIT=bfcbfbc
```

### 2. Frontend Rollback (Vercel / Cloudflare / Static CDN)
Revert production deployment instantaneously to previous build:
```bash
# Vercel CLI instant rollback
vercel rollback <PREVIOUS_DEPLOYMENT_URL> --yes

# Or re-deploy previous git tag
git checkout $PREV_STABLE_COMMIT
pnpm --prefix frontend build
# deploy artifact
```

### 3. Backend & Worker Rollback
Roll back container workloads:
```bash
# Kubernetes / Helm
helm rollback kova-production <PREVIOUS_REVISION>

# Or Docker Compose
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml pull
IMAGE_TAG=$PREV_STABLE_COMMIT docker compose -f docker-compose.prod.yml up -d
```

### 4. Database Schema Migration Downgrade (If Necessary)
If the new migration introduced incompatible column constraints:
```bash
# Check current migration revision
backend/.venv/bin/alembic current

# Downgrade one revision back
backend/.venv/bin/alembic downgrade -1
```

### 5. Verification & Health Check
Verify all services report healthy:
```bash
curl -f https://api.kova.dev/health/ready
# Expected: {"status": "ready"}

curl -f https://app.kova.dev/status
# Expected: All systems operational
```

### 6. Incident Retrospective
1. Notify customer support and update the status page incident note.
2. Export Sentry crash traces and Prometheus metrics during the outage window.
3. Schedule post-mortem with engineering within 24 hours.
