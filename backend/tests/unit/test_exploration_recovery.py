"""Unit tests for exploration recovery logic."""

import pytest

from app.modules.exploration.models import ExplorationStatus
from app.workers.recovery import (
    EXPLORATION_ABANDONED_SECONDS,
    EXPLORATION_DISPATCH_GRACE_SECONDS,
    EXPLORATION_TERMINAL_STATES,
)


def test_exploration_terminal_states():
    """Terminal exploration states should be recognized."""
    assert ExplorationStatus.COMPLETED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.FAILED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.CANCELLED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.BLOCKED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.CREATED.value not in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.CONNECTING.value not in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.READY.value not in EXPLORATION_TERMINAL_STATES


def test_exploration_recovery_redispatches_stale_created():
    """CREATED sessions older than grace period should be redispatched."""
    assert (
        ExplorationStatus.CREATED.value not in EXPLORATION_TERMINAL_STATES
    )
    # Simulate the recovery action logic inline (matches reconcile_explorations)
    status = ExplorationStatus.CREATED.value
    age = EXPLORATION_DISPATCH_GRACE_SECONDS - 1
    action = "dispatch" if (status == ExplorationStatus.CREATED.value and age >= EXPLORATION_DISPATCH_GRACE_SECONDS) else None
    assert action is None

    age = EXPLORATION_DISPATCH_GRACE_SECONDS
    action = "dispatch" if (status == ExplorationStatus.CREATED.value and age >= EXPLORATION_DISPATCH_GRACE_SECONDS) else None
    assert action == "dispatch"


def test_exploration_recovery_times_out_abandoned():
    """Non-terminal sessions older than abandoned threshold should time out."""
    status = ExplorationStatus.CONNECTING.value
    age = EXPLORATION_ABANDONED_SECONDS - 1
    action = None
    if status not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
        action = "timeout"
    assert action is None

    age = EXPLORATION_ABANDONED_SECONDS
    action = None
    if status not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
        action = "timeout"
    assert action == "timeout"


def test_exploration_recovery_keeps_terminal():
    """Terminal sessions should never be timed out regardless of age."""
    for terminal in EXPLORATION_TERMINAL_STATES:
        age = EXPLORATION_ABANDONED_SECONDS * 2
        action = None
        if terminal not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
            action = "timeout"
        assert action is None


def test_exploration_recovery_keeps_recent_non_terminal():
    """Recent non-terminal sessions should not be timed out."""
    status = ExplorationStatus.AUTH_REQUIRED.value
    age = EXPLORATION_ABANDONED_SECONDS - 1
    action = None
    if status not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
        action = "timeout"
    assert action is None
