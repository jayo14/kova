from app.modules.executions.models import ExecutionStatus
from app.workers.recovery import (
    ABANDONED_EXECUTION_SECONDS,
    DISPATCH_GRACE_SECONDS,
    _recovery_action,
)


def test_recovery_redispatches_only_stale_pending_records():
    assert _recovery_action(ExecutionStatus.CREATED.value, DISPATCH_GRACE_SECONDS - 1) is None
    assert _recovery_action(ExecutionStatus.CREATED.value, DISPATCH_GRACE_SECONDS) == "dispatch"
    assert _recovery_action(ExecutionStatus.QUEUED.value, DISPATCH_GRACE_SECONDS) == "dispatch"


def test_recovery_times_out_abandoned_running_records_but_keeps_recent_and_terminal():
    assert _recovery_action(ExecutionStatus.RUNNING.value, ABANDONED_EXECUTION_SECONDS - 1) is None
    assert _recovery_action(ExecutionStatus.RUNNING.value, ABANDONED_EXECUTION_SECONDS) == "timeout"
    assert _recovery_action(ExecutionStatus.CANCELLED.value, ABANDONED_EXECUTION_SECONDS * 2) is None


def test_recovery_fails_stuck_planning_and_prerequisites():
    from app.workers.recovery import PLANNING_TIMEOUT_SECONDS, PREREQUISITE_TIMEOUT_SECONDS

    assert _recovery_action(ExecutionStatus.PLANNING.value, PLANNING_TIMEOUT_SECONDS - 1) is None
    assert _recovery_action(ExecutionStatus.PLANNING.value, PLANNING_TIMEOUT_SECONDS) == "fail_planning"

    assert _recovery_action(ExecutionStatus.RESOLVING_PREREQUISITES.value, PREREQUISITE_TIMEOUT_SECONDS - 1) is None
    assert _recovery_action(ExecutionStatus.RESOLVING_PREREQUISITES.value, PREREQUISITE_TIMEOUT_SECONDS) == "fail_prerequisites"

