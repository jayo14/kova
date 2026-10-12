# Phase 1 reliability and deployment notes

## Browser egress boundary

Playwright context routing checks every HTTP request and redirect, blocks service
workers, checks WebSocket destinations, and rejects private, loopback (in
production), link-local, reserved, and metadata addresses. This is a useful
application-level defense, but it cannot fully prevent DNS rebinding: Chromium
resolves a hostname separately after the application checks its DNS answers.
Deploy browser workers in a network namespace/container with outbound rules that
deny loopback, RFC1918, IPv6 ULA/link-local, carrier-grade NAT, cloud metadata,
and Kova's API, database, Redis, object storage control plane, and other internal
service ranges. Do not give browser workers host networking or an unrestricted
egress proxy. The application check is not a substitute for those network rules.

## Execution recovery

The API lifespan watchdog runs every 30 seconds. It redispatches pending
`CREATED`/`QUEUED` rows older than 45 seconds and marks non-terminal rows with
no persisted update for 11 minutes as `TIMEOUT`. Workers claim rows under a
database row lock before starting a browser, so duplicate broker delivery does
not start a second run. The recovery loop requires a continuously running API
process and PostgreSQL; readiness now requires PostgreSQL, Redis, and at least
one responding Celery worker.

## Required deployment configuration

- Set `ENVIRONMENT=production`, a unique `JWT_SECRET_KEY` of at least 32
  characters, and a valid Fernet `CREDENTIAL_ENCRYPTION_KEY` from a secret
  manager. Keep the credential key stable across deploys; rotating it requires
  an explicit migration/key-version strategy.
- Enforce browser-worker egress restrictions described above at the network
  layer. URL validation alone does not eliminate DNS rebinding.
- Run the execution recovery API process alongside at least one Celery worker.
  Liveness is `/health/live`; readiness is `/health/ready` (also
  `/api/v1/health/ready`).
- Protect the configured production CORS origins and use HTTPS at the frontend
  and API ingress. Authentication uses bearer tokens, so cross-origin cookies
  are not required by the current API.
