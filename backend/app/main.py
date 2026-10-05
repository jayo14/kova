from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, ci, credentials, executions, exploration, flows, projects, viewport
from app.config.settings import settings

# Uvicorn's default logging config leaves the root logger without
# handlers, so application INFO logs (e.g. execution dispatch) are
# silently dropped. Give the root logger a handler so dispatch and
# engine lifecycle events are actually observable.
logging.basicConfig(
    level=logging.INFO if (settings.DEBUG and not settings.is_production) else logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
from app.infrastructure.database.session import engine


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
