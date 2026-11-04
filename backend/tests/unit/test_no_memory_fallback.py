import os
from unittest import mock
import pytest

from app.engine.execution.control import (
    RedisUnavailableError,
    get_control_record,
    save_control_record,
    queue_user_input,
    publish_command,
    ControlRecord,
    is_service_degraded,
    mark_service_degraded,
)


@pytest.mark.asyncio
async def test_no_in_memory_control_fallback_in_multiprocess():
    mark_service_degraded(False)
    # Simulate multi-process environment (e.g. KOVA_ROLE=api) with Redis down
    with mock.patch.dict(os.environ, {"KOVA_ROLE": "api"}):
        with mock.patch("app.engine.execution.control._get_redis", return_value=None):
            # Attempting to get control record must raise RedisUnavailableError and mark degraded
            with pytest.raises(RedisUnavailableError):
                await get_control_record("exec-123")
            assert is_service_degraded() is True

            # Attempting to save control record must also raise RedisUnavailableError
            rec = ControlRecord(execution_id="exec-123")
            with pytest.raises(RedisUnavailableError):
                await save_control_record(rec)

            # Queueing user input must also fail loudly
            with pytest.raises(RedisUnavailableError):
                await queue_user_input("exec-123", {"action": "click"})

            # Publishing command must also fail loudly
            with pytest.raises(RedisUnavailableError):
                await publish_command("exec-123", "pause")
