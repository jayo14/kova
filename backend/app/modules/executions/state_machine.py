"""Execution state machine.

Defines valid transitions between execution states.
Terminal states have no outgoing transitions.
"""


class InvalidTransitionError(Exception):
    def __init__(self, current_status: str, attempted_status: str):
        self.current_status = current_status
        self.attempted_status = attempted_status
        super().__init__(
            f"Invalid transition: {current_status} -> {attempted_status}"
        )


# Valid transitions between states
# CANCELLED can be reached from any non-terminal state
VALID_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"QUEUED", "PLANNING", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "QUEUED": {"INITIALIZING", "PLANNING", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "INITIALIZING": {"BROWSER_READY", "PLANNING", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "BROWSER_READY": {"PLANNING", "RESOLVING_PREREQUISITES", "CONTAMINATION_DETECTED", "RUNNING", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "PLANNING": {"BROWSER_READY", "RESOLVING_PREREQUISITES", "RUNNING", "PREREQUISITE_FAILED", "UNVERIFIED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "RESOLVING_PREREQUISITES": {"RESOLVING_PREREQUISITES", "CONTAMINATION_DETECTED", "RUNNING", "PREREQUISITE_FAILED", "UNVERIFIED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "PREREQUISITE_FAILED": {"PAUSED", "UNVERIFIED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "CONTAMINATION_DETECTED": {"RESOLVING_PREREQUISITES", "RUNNING", "UNVERIFIED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"},
    "RUNNING": {"WAITING", "PAUSED", "HUMAN_CONTROLLED", "CONTAMINATION_DETECTED", "COMPLETED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT", "BLOCKED", "UNVERIFIED"},
    "WAITING": {"RUNNING", "PAUSED", "HUMAN_CONTROLLED", "FAILED", "ERROR", "TIMEOUT", "CANCELLED"},
    "PAUSED": {"HUMAN_CONTROLLED", "RESUMING", "CANCELLED", "FAILED", "ERROR", "TIMEOUT", "PREREQUISITE_FAILED"},
    "HUMAN_CONTROLLED": {"RESUMING", "CANCELLED", "FAILED", "ERROR", "TIMEOUT"},
    "RESUMING": {"RUNNING", "OBSERVING", "PLANNING", "RESOLVING_PREREQUISITES", "FAILED", "ERROR", "TIMEOUT"},
    "COMPLETED": set(),
    "FAILED": set(),
    "ERROR": set(),
    "CANCELLED": set(),
    "TIMEOUT": set(),
    "BLOCKED": set(),
    "NEEDS_INPUT": {"RUNNING", "FAILED", "CANCELLED", "TIMEOUT"},
    "UNVERIFIED": set(),
}

TERMINAL_STATES = {"COMPLETED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT", "BLOCKED", "UNVERIFIED"}


def validate_transition(current_status: str, new_status: str) -> None:
    """Validate if a state transition is allowed.

    Raises:
        InvalidTransitionError if transition is not allowed.
    """
    allowed = VALID_TRANSITIONS.get(current_status)
    if allowed is None:
        raise InvalidTransitionError(current_status, new_status)
    if new_status not in allowed:
        raise InvalidTransitionError(current_status, new_status)


def is_terminal(status: str) -> bool:
    """Check if a state is terminal (no outgoing transitions)."""
    return status in TERMINAL_STATES
