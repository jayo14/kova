# Kova

Autonomous software-use and product-flow execution platform. Give Kova a URL, credentials, and a goal; it opens an isolated Playwright browser, explores the application, discovers workflows, executes product journeys, and records verifiable step-by-step evidence.

## Why it matters

Manual QA and exploratory testing do not scale. Kova acts as an autonomous user: it navigates real UIs, handles logins, runs journeys, and captures evidence (screenshots, audit logs, network requests) so teams can verify product behavior without writing brittle scripts.

## Differentiators

- Isolated browser execution: each run uses a dedicated Chromium context inside a Celery worker; the API never launches browsers.
- Evidence-backed verification: success is proven by deterministic checks, not by "an action was attempted".
- Live run visibility: real-time viewport frames and telemetry stream to the dashboard.
- AI proposes, code disposes: model output is validated into typed schemas before any browser action; only deterministic verification can mark a run complete.

## Quick start (Docker Compose)

Prerequisites: Docker 24+ and Docker Compose v2. (Docker is not installed here; see [manual setup](docs/local-setup.md).)

```bash
cp .env.example backend/.env
# edit backend/.env (at minimum DATABASE_URL or use compose defaults)
docker compose up -d
```

Services: frontend http://localhost:3000, API http://localhost:8000, health http://localhost:8000/health.

## Manual setup

See [docs/local-setup.md](docs/local-setup.md) for Windows/macOS/Linux steps.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Smoke test

```bash
cd backend && .venv/bin/pytest tests/smoke/ -v
```

## License

MIT License. See [LICENSE](LICENSE).