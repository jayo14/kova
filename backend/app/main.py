from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import sentry_sdk

from app.api.routes import auth, ci, credentials, executions, exploration, flows, projects, viewport
from app.config.settings import settings
from app.infrastructure.database.session import engine


# Initialize Sentry SDK before FastAPI app initialization
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profile_session_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        profile_lifecycle="trace",
        environment=settings.ENVIRONMENT,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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


@app.get("/")
@app.get("/health")
@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.get("/sentry-debug")
@app.get("/sentry-debug/")
async def trigger_error():
    division_by_zero = 1 / 0
    return {"result": division_by_zero}
