# Kova Production Launch Checklist

This master launch checklist verifies operational, security, product, and reliability readiness for Kova v0.1.0 production release.

---

## 1. Product & Customer Journeys

- [x] **Sign Up & Auth**: A new user can register, receive JWT tokens, and access the dashboard in under 2 minutes.
- [x] **First-Run Onboarding**: The 4-step wizard guides the user through app connection, test credentials, autonomous discovery, and baseline validation in under 10 minutes.
- [x] **Skippable Wizard**: Users can skip or resume the onboarding wizard at any time (`PATCH /api/v1/auth/me/onboarding`).
- [x] **GitHub Integration**: A user can connect a GitHub repository in under 1 minute via the integration UI.
- [x] **CI PR Feedback**: PR opened / synchronize events trigger targeted continuous validation and post explanatory comments with visual health badges within 5 minutes.
- [x] **Billing & Subscriptions**: Users can self-serve upgrade from Free to Pro or Enterprise via Stripe Checkout.
- [x] **Quotas & Metering**: Quotas update automatically upon Stripe webhook confirmation (`checkout.session.completed`, `customer.subscription.deleted`).
- [x] **API Tokens**: Users can generate scoped API tokens (`ci:validate`, `projects:read`, `org:manage`, `*`), copy them once upon creation, and revoke them anytime.

---

## 2. Security & Compliance Invariants (`AUDIT.md` Verification)

- [x] **JWT Secret Strength**: Production requires `JWT_SECRET_KEY` length $\ge 32$ characters.
- [x] **Dev-User Fallback Disabled**: Dev-user bypass is strictly disabled when `ENVIRONMENT=production`.
- [x] **Credential Encryption at Rest**: Encrypted using Fernet; master keys never stored in plaintext.
- [x] **Tenant Cryptographic Isolation**: Enterprise tenants use dedicated Data Encryption Keys (DEKs) wrapped by the master key.
- [x] **Memory-Only Decryption**: Decrypted credentials exist solely in worker process memory during active test sessions.
- [x] **SSRF Protection with DNS Pre-Resolution**: Loopback (`127.0.0.1`), private RFC1918 ranges, and cloud metadata IPs (`169.254.169.254`) are blocked prior to HTTP connection.
- [x] **AI Governance**: AI suggestions cannot mark execution status `COMPLETED` or bypass invariant checks.
- [x] **Vacuous-Condition Rejection**: Assertions without observable preconditions or assertions with 0 elements fail closed.
- [x] **Signed Reports**: CI validation reports are tamper-proofed with HMAC-SHA256 signatures.
- [x] **Audit Log Scrubbing**: Passwords, bearer tokens, API tokens, cookies, and secret keys are recursively redacted in audit records.
- [x] **Observability Log Scrubbing**: Central `RedactionFilter` scrubs sensitive keys before logs reach stdout/Sentry.
- [x] **Webhook Signature Verification**: GitHub (`X-Hub-Signature-256`), GitLab (`X-Gitlab-Token`), and Stripe (`Stripe-Signature`) headers are verified before processing.
- [x] **Plan Limit Enforcement**: Free-tier organizations exceeding 50 executions/month receive HTTP 402 with an upgrade link.
- [x] **No Mock or Demo Routes in Production**: Demo routes are purged from production API routing.

---

## 3. Reliability & Graceful Degradation

- [x] **Zombie Execution Recovery**: Periodic background loop reaps stuck `PLANNING` (>30s) and `RUNNING` (>300s) executions every 30 seconds.
- [x] **Redis Degradation**: Frame streaming drops gracefully to memory buffer if Redis is temporarily unreachable.
- [x] **S3 Degradation**: S3 upload failures persist local evidence files and log warning notes without aborting test execution.
- [x] **AI Provider Outage**: When AI APIs are unreachable, deterministic graph-walking fallbacks execute seamlessly.
- [x] **Database Connectivity**: `/health/ready` validates database connectivity and worker availability, returning 503 if unreachable.
- [x] **Database Connection Pooling**: Configured with overflow protection and pool recycling.

---

## 4. Observability & SRE Runbooks

- [x] **Prometheus Metrics**: `GET /metrics` serves standard Prometheus metrics (`http_requests_total`, `executions_completed_total`, `worker_queue_depth`, etc.) protected by IP allowlisting.
- [x] **Distributed Tracing**: OpenTelemetry traces child spans for execution planning, prerequisite resolution, target execution, and verification.
- [x] **Structured JSON Logging**: All logs include `request_id`, `trace_id`, and `org_id`.
- [x] **Alerting Rules**: `docs/alerts/kova-alerts.yml` covers queue backup, error rate spikes, worker failure, and latency anomalies.
- [x] **Grafana Dashboards**: `docs/dashboards/kova-overview.json` and `docs/dashboards/kova-execution-detail.json` ready for production import.
- [x] **Operational Runbooks**:
  - `docs/runbooks/worker-queue-backup.md`
  - `docs/runbooks/s3-upload-failures.md`
  - `docs/runbooks/postgres-connection-exhaustion.md`
  - `docs/runbooks/browser-crash-loop.md`
  - `docs/runbooks/launch-rollback.md`

---

## 5. Documentation & Public Surfaces

- [x] **Docs Site**: Mintlify documentation site in `docs-site/` with Quickstart, Concepts, Integrations, API Reference, and Pricing.
- [x] **Public Status Page**: `frontend/app/status/page.tsx` displaying live service component telemetry and health.
- [x] **README & PRD**: Up-to-date developer and product documentation reflecting the Product Graph architecture.
- [x] **ADR-002**: Architectural Decision Record documenting the Product Graph as Kova's core intellectual property.

---

## 6. Launch Operations Checklist

- [x] **Environment Variables Configured**:
  - `ENVIRONMENT=production`
  - `JWT_SECRET_KEY` (length $\ge 32$)
  - `CREDENTIAL_ENCRYPTION_KEY`
  - `STRIPE_SECRET_KEY` & `STRIPE_WEBHOOK_SECRET`
  - `GITHUB_APP_PRIVATE_KEY` & `GITHUB_WEBHOOK_SECRET`
  - `OTEL_EXPORTER_OTLP_ENDPOINT`
  - `SENTRY_DSN`
- [x] **Automated Smoke Test Suite**: All tests in `backend/tests/smoke/` pass with exit code 0.
