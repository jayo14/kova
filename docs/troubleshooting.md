# Troubleshooting

- Port conflicts: change ports in docker-compose or uvicorn/npm.
- Missing env vars: ensure backend/.env exists and required vars set.
- DB connectivity: verify DATABASE_URL and postgres health.
- Failed migrations: run `alembic upgrade head` manually; check logs.
- Browser execution: ensure `playwright install chromium` and system deps; worker must be running or executions stay CREATED.
- Docker resource limits: each browser ~1-1.5GB; concurrency 2.
- Redis: ensure redis reachable; frames ephemeral.
- Frontend can't reach API: check NEXT_PUBLIC_API_URL.
