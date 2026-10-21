"""Local fixture server utility for serving ASGI/FastAPI applications on ephemeral ports."""

import asyncio
import socket
import logging
from typing import AsyncGenerator
import uvicorn
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


def find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FixtureServer:
    """Runs a fixture FastAPI app in an asyncio background task."""

    def __init__(self, app, host: str = "127.0.0.1", port: int | None = None):
        self.app = app
        self.host = host
        self.port = port or find_free_port()
        self.base_url = f"http://{self.host}:{self.port}"
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> str:
        """Start the server and wait until it responds."""
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="error",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())

        # Wait for server to bind and be ready
        for _ in range(50):
            if self._server.started:
                break
            await asyncio.sleep(0.05)

        return self.base_url

    async def stop(self) -> None:
        """Stop the server cleanly."""
        if self._server:
            self._server.should_exit = True
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._task = None
        self._server = None


@asynccontextmanager
async def serve_fixture(app, host: str = "127.0.0.1", port: int | None = None) -> AsyncGenerator[str, None]:
    """Context manager for serving a fixture app during a benchmark run."""
    server = FixtureServer(app, host=host, port=port)
    base_url = await server.start()
    try:
        yield base_url
    finally:
        await server.stop()
