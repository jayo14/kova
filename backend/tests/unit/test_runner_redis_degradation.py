import uuid
from unittest.mock import patch
import pytest

from app.engine.execution.runner import FlowRunner
from app.engine.browser.session import BrowserSession


@pytest.mark.asyncio
async def test_runner_degrades_gracefully_on_redis_frame_broadcast_failure():
    """Verify runner degrades gracefully, without aborting, when Redis frame broadcast fails."""
    runner = FlowRunner()

    with patch("app.engine.execution.runner.publish_frame", side_effect=Exception("Redis connection refused")):
        with patch.object(BrowserSession, "navigate", return_value=None):
            with patch.object(BrowserSession, "close", return_value=None):
                result = await runner.execute(
                    execution_id=uuid.uuid4(),
                    flow_steps=[],
                    target_url="http://example.com",
                    success_condition={"url_matches": ".*"},
                )
                # The execution should not abort or crash; it should complete
                assert result is not None
                assert result.get("state") in ("COMPLETED", "FAILED")
                assert "Redis connection refused" not in result.get("error", "")
