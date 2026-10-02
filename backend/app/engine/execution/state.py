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
    RUNNING = "RUNNING"
    OBSERVING = "OBSERVING"
    ACTING = "ACTING"
    PAUSED = "PAUSED"
    HUMAN_CONTROLLED = "HUMAN_CONTROLLED"
    RESUMING = "RESUMING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Valid state transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    ExecutionState.IDLE: [ExecutionState.QUEUED, ExecutionState.FAILED],
    ExecutionState.QUEUED: [ExecutionState.INITIALIZING, ExecutionState.FAILED],
    ExecutionState.INITIALIZING: [ExecutionState.BROWSER_READY, ExecutionState.FAILED],
    ExecutionState.BROWSER_READY: [ExecutionState.RUNNING, ExecutionState.FAILED],
    ExecutionState.RUNNING: [
        ExecutionState.OBSERVING,
        ExecutionState.ACTING,
        ExecutionState.PAUSED,
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
    ],
    ExecutionState.OBSERVING: [
        ExecutionState.OBSERVING,
        ExecutionState.ACTING,
        ExecutionState.PAUSED,
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
    ],
    ExecutionState.ACTING: [
        ExecutionState.ACTING,
        ExecutionState.OBSERVING,
        ExecutionState.PAUSED,
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
    ],
    ExecutionState.PAUSED: [
        ExecutionState.HUMAN_CONTROLLED,
        ExecutionState.RESUMING,
        ExecutionState.FAILED,
    ],
    ExecutionState.HUMAN_CONTROLLED: [
        ExecutionState.RESUMING,
        ExecutionState.FAILED,
    ],
    ExecutionState.RESUMING: [
        ExecutionState.RUNNING,
        ExecutionState.OBSERVING,
        ExecutionState.FAILED,
    ],
    ExecutionState.VERIFYING: [
        ExecutionState.VERIFYING,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
    ],
    ExecutionState.COMPLETED: [],
    ExecutionState.FAILED: [],
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
    return state in (ExecutionState.COMPLETED.value, ExecutionState.FAILED.value)
