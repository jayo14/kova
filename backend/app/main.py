from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from sqlalchemy import text
from redis.asyncio import Redis

import sentry_sdk

from app.api.routes import (
    auth,
    billing,
    ci,
    credentials,
    executions,
    exploration,
    flows,
    integrations,
    metrics,
    organizations,
    projects,
    usage,
    viewport,
)
from app.config.settings import settings
from app.infrastructure.database.session import engine
from app.modules.auth.rate_limiter import rate_limiter
from app.observability.logging import RequestIdMiddleware, configure_logging
from app.observability.metrics import PrometheusMiddleware
from app.observability.tracing import FastAPITracingMiddleware, configure_tracing

# Initialize structured logging and OpenTelemetry tracing
configure_logging()
configure_tracing()


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

# Core Observability middlewares: Request ID, Tracing, and Prometheus Metrics
app.add_middleware(RequestIdMiddleware)
app.add_middleware(FastAPITracingMiddleware)
app.add_middleware(PrometheusMiddleware)

import logging
from fastapi.responses import JSONResponse
from fastapi import Request

logger = logging.getLogger(__name__)

# CORS: restrict in production, allow all in development
if settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
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


def _cors_headers_for_request(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if settings.is_production:
        if origin in settings.cors_origins_list:
            return {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
            }
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
    }


from app.observability.redaction import redact

@app.middleware("http")
async def cors_exception_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            headers = _cors_headers_for_request(request)
            if exc.headers:
                headers.update(exc.headers)
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=headers,
            )
        # Never log raw sensitive exception details in production
        exc_msg = "[hidden in production]" if settings.is_production else redact(str(exc))
        logger.exception("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc_msg)
        headers = _cors_headers_for_request(request)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error" if settings.is_production else str(exc)},
            headers=headers,
        )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    headers = _cors_headers_for_request(request)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error" if settings.is_production else str(exc)},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        headers = _cors_headers_for_request(request)
        if exc.headers:
            headers.update(exc.headers)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )
    exc_msg = "[hidden in production]" if settings.is_production else redact(str(exc))
    logger.exception("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc_msg)
    return await server_error_handler(request, exc)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Exclude health endpoints, docs, metrics, and CI endpoints
    path = request.url.path
    if (
        path.startswith("/health")
        or path in ("/api/v1/health", "/api/v1/health/ready", "/", "/docs", "/openapi.json", "/redoc", "/metrics")
        or path.startswith("/api/v1/ci")
    ):
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    token = request.headers.get("x-api-key") or (auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else "")
    client_id = f"tok_{token[:16]}" if token else (request.client.host if request.client else "anon")

    allowed, retry_after = await rate_limiter.check_user_rate_limit(client_id, limit=60, window_seconds=60)
    if not allowed:
        headers = _cors_headers_for_request(request)
        headers["Retry-After"] = str(retry_after)
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers=headers,
        )
    return await call_next(request)


app.include_router(auth.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(organizations.router, prefix="/api/v1")
app.include_router(organizations.project_members_router, prefix="/api/v1")
app.include_router(ci.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(credentials.router, prefix="/api/v1")
app.include_router(flows.router, prefix="/api/v1")
app.include_router(executions.router, prefix="/api/v1")
app.include_router(executions.validations_router, prefix="/api/v1")
app.include_router(executions.evidence_router, prefix="/api/v1")
app.include_router(integrations.router, prefix="/api/v1")
app.include_router(integrations.project_integrations_router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")
app.include_router(exploration.router, prefix="/api/v1")
app.include_router(metrics.router)
app.include_router(viewport.router)


@app.get("/")
@app.get("/health/live")
@app.get("/health")
@app.get("/api/v1/health")
async def liveness():
    return {
        "status": "ok",
        "service": "kova-backend",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
    }


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
