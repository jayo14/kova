from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from sqlalchemy import text
from redis.asyncio import Redis

import sentry_sdk

from app.api.routes import auth, ci, credentials, executions, exploration, flows, projects, viewport
from app.config.settings import settings
from app.infrastructure.database.session import engine


# Initialize Sentry SDK before FastAPI app initialization
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=False,
        enable_logs=True,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profile_session_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        profile_lifecycle="trace",
        environment=settings.ENVIRONMENT,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.workers.recovery import recovery_loop

    recovery_task = asyncio.create_task(recovery_loop(), name="execution-recovery")
    try:
        yield
    finally:
        recovery_task.cancel()
        try:
            await recovery_task
        except asyncio.CancelledError:
            pass
        # Dispose engine pool on shutdown — prevents CancelledError on stale connections
        await engine.dispose()


app = FastAPI(
    title="Kova",
    description="Autonomous software-use and product-flow execution platform",
    version="0.1.0",
    debug=settings.DEBUG and not settings.is_production,
    lifespan=lifespan,
)

# CORS: restrict in production, allow all in development
if settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(ci.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(credentials.router, prefix="/api/v1")
app.include_router(flows.router, prefix="/api/v1")
app.include_router(executions.router, prefix="/api/v1")
app.include_router(exploration.router, prefix="/api/v1")
app.include_router(viewport.router)


@app.get("/health/live")
@app.get("/health")
@app.get("/api/v1/health")
async def liveness():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.get("/health/ready")
@app.get("/api/v1/health/ready")
async def readiness():
    """Report readiness only when the database and Redis are reachable."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        redis = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        try:
            await redis.ping()
        finally:
            await redis.aclose()
        from app.workers.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1)
        workers = await asyncio.to_thread(inspector.ping) if inspector else None
        if not workers:
            raise RuntimeError("No execution workers are available")
    except Exception:
        raise HTTPException(status_code=503, detail="Service dependencies unavailable")
    return {"status": "ready"}
