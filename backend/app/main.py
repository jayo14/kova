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
    runs,
    usage,
    viewport,
)
from app.config.settings import settings
from app.infrastructure.database.session import engine
from app.modules.auth.rate_limiter import rate_limiter, token_bucket_key
from app.observability.logging import RequestIdMiddleware, configure_logging
from app.observability.metrics import PrometheusMiddleware
from app.observability.tracing import FastAPITracingMiddleware, configure_tracing

# Initialize structured logging and OpenTelemetry tracing
configure_logging()
configure_tracing()


def _sentry_before_send(event: dict, hint: dict) -> dict | None:
    # Ignore exceptions originating solely from one-off CLI evaluations (<string>) in development
    try:
        frames = (
            event.get("exception", {})
            .get("values", [{}])[0]
            .get("stacktrace", {})
            .get("frames", [])
        )
        if frames and len(frames) == 1 and frames[0].get("filename") == "<string>":
            return None
    except Exception:
        pass
    return event


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
        before_send=_sentry_before_send,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.workers.recovery import recovery_loop
    from app.infrastructure.database.migrations import verify_database_schema
    from app.infrastructure.database.session import async_session_factory

    try:
        async with async_session_factory() as session:
            await verify_database_schema(session)
    except Exception as exc:
        logging.getLogger(__name__).warning("Database schema pre-check encountered an issue: %s", exc)

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

import re

def _is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    if not settings.is_production:
        return True
    clean = origin.rstrip("/")
    if clean in [o.rstrip("/") for o in settings.cors_origins_list]:
        return True
    if re.match(r"^https://([a-zA-Z0-9_-]+\.)*(kova\.app|vercel\.app|rumptycloud\.app)$", clean):
        return True
    return False


# CORS: restrict in production with regex, allow all in development
if settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=r"https://.*(kova\.app|vercel\.app|rumptycloud\.app).*",
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
    if _is_allowed_origin(origin):
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    return {}


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
    # Always allow CORS preflights through immediately
    if request.method == "OPTIONS":
        return await call_next(request)

    # Exclude health endpoints, docs, metrics, and CI endpoints
    path = request.url.path
    if (
        path.startswith("/health")
        or path in ("/api/v1/health", "/api/v1/health/ready", "/", "/docs", "/openapi.json", "/redoc", "/metrics")
        or path.startswith("/api/v1/ci")
    ):
        return await call_next(request)

    real_ip = request.headers.get("cf-connecting-ip") or request.headers.get("x-real-ip")
    forwarded = request.headers.get("x-forwarded-for")
    if real_ip:
        client_ip = real_ip.strip()
    elif forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "anon"

    auth_header = request.headers.get("authorization", "")
    token = request.headers.get("x-api-key") or (auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else "")
    client_id = token_bucket_key(token) if token else f"ip_{client_ip}"

    # Generous limits for active exploration sessions, SSE streams, and auth verification
    is_exploration_or_auth = path.startswith("/api/v1/exploration") or path in ("/api/v1/auth/me", "/auth/me")

    # In development or debug, use generous limit (1200 req/min).
    # In production, use higher limit (1200 req/min) for exploration/auth/authenticated tokens so live streams and polls never get throttled.
    base_limit = getattr(app.state, "rate_limit_override", None) or (
        1200 if (not settings.is_production or settings.DEBUG) else settings.RATE_LIMIT_PER_MINUTE
    )
    limit = max(base_limit, 1200) if (token or is_exploration_or_auth) else base_limit
    allowed, retry_after = await rate_limiter.check_user_rate_limit(client_id, limit=limit, window_seconds=60)
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
app.include_router(runs.router, prefix="/api/v1")
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
    """Report readiness only when dependencies are reachable, reporting live integration status."""
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
    except Exception as e:
        raise HTTPException(status_code=503, detail="Service dependencies unavailable")

    from app.modules.billing.stripe_client import StripeClient
    from app.modules.email.service import EmailService

    stripe_live = StripeClient().is_configured()
    stripe_webhook_live = bool(settings.STRIPE_WEBHOOK_SECRET and settings.STRIPE_WEBHOOK_SECRET != "mock_secret")
    ses_live = EmailService().is_configured

    integrations = {
        "database": True,
        "redis": True,
        "celery": True,
        "stripe": stripe_live,
        "stripe_webhook": stripe_webhook_live,
        "ses": ses_live,
    }

    if settings.is_production:
        missing = []
        if not stripe_live:
            missing.append("stripe")
        if not stripe_webhook_live:
            missing.append("stripe_webhook")
        if not ses_live:
            missing.append("ses")
        if missing:
            raise HTTPException(
                status_code=503,
                detail=f"Production readiness failed: missing required integrations ({', '.join(missing)})",
            )

    return {
        "status": "ready",
        "integrations": integrations,
    }
