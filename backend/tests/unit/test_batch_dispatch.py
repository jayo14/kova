from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.tasks import _run_multiple_executions_async


@pytest.mark.asyncio
async def test_batch_delegates_each_execution_to_run_execution_async():
    with patch(
        "app.workers.tasks.executions._run_execution_async",
        new_callable=AsyncMock,
        return_value={"status": "succeeded"},
    ) as mock_run:
        result = await _run_multiple_executions_async(None, ["e1", "e2"], parallel=False)

    assert mock_run.await_count == 2
    assert [c.args[1] for c in mock_run.await_args_list] == ["e1", "e2"]
    assert result["count"] == 2
    assert result["parallel"] is False
    assert [r["status"] for r in result["results"]] == ["succeeded", "succeeded"]


@pytest.mark.asyncio
async def test_batch_parallel_invokes_all_executions():
    with patch(
        "app.workers.tasks.executions._run_execution_async",
        new_callable=AsyncMock,
        return_value={"status": "succeeded"},
    ) as mock_run:
        result = await _run_multiple_executions_async(None, ["a", "b", "c"], parallel=True)

    assert mock_run.await_count == 3
    assert result["parallel"] is True
    assert result["count"] == 3


@pytest.mark.asyncio
async def test_batch_captures_unknown_execution_as_failed_result():
    async def _raise(task, exec_id):
        if exec_id == "missing":
            raise ValueError("Execution missing not found")
        return {"status": "succeeded", "execution_id": exec_id}

    with patch(
        "app.workers.tasks.executions._run_execution_async",
        new_callable=AsyncMock,
        side_effect=_raise,
    ):
        result = await _run_multiple_executions_async(None, ["missing", "ok"], parallel=True)

    by_id = {r["execution_id"]: r for r in result["results"]}
    assert by_id["missing"]["status"] == "failed"
    assert "not found" in by_id["missing"]["error"]
    assert by_id["ok"]["status"] == "succeeded"
