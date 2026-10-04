import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.execution.runner import FlowRunner
from tests.test_app import app as test_app


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_test_server():
    port = _get_free_port()
    config = uvicorn.Config(test_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def test_server():
    async with _run_test_server() as url:
        yield url


@pytest.mark.asyncio
async def test_vacuous_expectation_results_in_unverified_run(test_server):
    """If compiled expectation is vacuous, runner must report UNVERIFIED, never PASSED."""
    runner = FlowRunner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        target_url=test_server,
        objective="Look around",
        expected_outcome="main container exists",
    )
    assert result["success"] is False
    assert result["error_code"] == "UNVERIFIED"
    assert result["state"] == "COMPLETED"
    assert result["verification"]["passed"] is False
    check_types = [c["type"] for c in result["verification"]["checks"]]
    assert "vacuous_condition" in check_types or "no_condition" in check_types
