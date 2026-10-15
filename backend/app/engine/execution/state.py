"""Execution state machine.

States follow the execution lifecycle:
IDLE → QUEUED → INITIALIZING → BROWSER_READY → RUNNING → COMPLETED/FAILED
"""

import enum


class ExecutionState(str, enum.Enum):
    """Internal execution states for the runner."""

    IDLE = "IDLE"
    QUEUED = "QUEUED"
    INITIALIZING = "INITIALIZING"
    BROWSER_READY = "BROWSER_READY"
    PLANNING = "PLANNING"
    RESOLVING_PREREQUISITES = "RESOLVING_PREREQUISITES"
    PREREQUISITE_FAILED = "PREREQUISITE_FAILED"
    CONTAMINATION_DETECTED = "CONTAMINATION_DETECTED"
    RUNNING = "RUNNING"
    OBSERVING = "OBSERVING"
    ACTING = "ACTING"
    PAUSED = "PAUSED"
    HUMAN_CONTROLLED = "HUMAN_CONTROLLED"
    RESUMING = "RESUMING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


# Valid state transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    ExecutionState.IDLE: [ExecutionState.QUEUED, ExecutionState.FAILED],
    ExecutionState.QUEUED: [ExecutionState.INITIALIZING, ExecutionState.PLANNING, ExecutionState.FAILED],
    ExecutionState.INITIALIZING: [ExecutionState.BROWSER_READY, ExecutionState.PLANNING, ExecutionState.FAILED],
    ExecutionState.BROWSER_READY: [
        ExecutionState.PLANNING,
        ExecutionState.RESOLVING_PREREQUISITES,
        ExecutionState.CONTAMINATION_DETECTED,
        ExecutionState.RUNNING,
        ExecutionState.FAILED,
    ],
    ExecutionState.PLANNING: [
        ExecutionState.BROWSER_READY,
        ExecutionState.RESOLVING_PREREQUISITES,
        ExecutionState.RUNNING,
        ExecutionState.PREREQUISITE_FAILED,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.RESOLVING_PREREQUISITES: [
        ExecutionState.RESOLVING_PREREQUISITES,
        ExecutionState.CONTAMINATION_DETECTED,
        ExecutionState.OBSERVING,
        ExecutionState.ACTING,
        ExecutionState.RUNNING,
        ExecutionState.PREREQUISITE_FAILED,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.PREREQUISITE_FAILED: [
        ExecutionState.PAUSED,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.CONTAMINATION_DETECTED: [
        ExecutionState.RESOLVING_PREREQUISITES,
        ExecutionState.OBSERVING,
        ExecutionState.ACTING,
        ExecutionState.RUNNING,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.RUNNING: [
        ExecutionState.OBSERVING,
        ExecutionState.ACTING,
        ExecutionState.PAUSED,
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.CONTAMINATION_DETECTED,
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.OBSERVING: [
        ExecutionState.OBSERVING,
        ExecutionState.ACTING,
        ExecutionState.RESOLVING_PREREQUISITES,
        ExecutionState.RUNNING,
        ExecutionState.PAUSED,
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.CONTAMINATION_DETECTED,
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.ACTING: [
        ExecutionState.ACTING,
        ExecutionState.OBSERVING,
        ExecutionState.RESOLVING_PREREQUISITES,
        ExecutionState.RUNNING,
        ExecutionState.PAUSED,
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.CONTAMINATION_DETECTED,
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.PAUSED: [
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.RESUMING,
        ExecutionState.PREREQUISITE_FAILED,
        ExecutionState.FAILED,
    ],
    ExecutionState.HUMAN_CONTROLLED: [
        ExecutionState.RESUMING,
        ExecutionState.FAILED,
    ],
    ExecutionState.RESUMING: [
        ExecutionState.RUNNING,
        ExecutionState.OBSERVING,
        ExecutionState.PLANNING,
        ExecutionState.RESOLVING_PREREQUISITES,
        ExecutionState.FAILED,
    ],
    ExecutionState.VERIFYING: [
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.UNVERIFIED,
    ],
    ExecutionState.COMPLETED: [],
    ExecutionState.FAILED: [],
    ExecutionState.UNVERIFIED: [],
}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state} → {to_state}")


def validate_transition(from_state: str, to_state: str) -> bool:
    """Validate if a state transition is allowed.

    Returns:
        True if transition is valid.

    Raises:
        InvalidTransitionError if transition is not allowed.
    """
    if from_state == to_state:
        return True
    valid = VALID_TRANSITIONS.get(from_state, [])
    if to_state not in valid:
        raise InvalidTransitionError(from_state, to_state)
    return True


def is_terminal(state: str) -> bool:
    """Check if a state is terminal (no further transitions)."""
    return state in (
        ExecutionState.COMPLETED.value,
        ExecutionState.FAILED.value,
        ExecutionState.UNVERIFIED.value,
    )
