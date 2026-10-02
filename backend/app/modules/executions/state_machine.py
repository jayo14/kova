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
    "CREATED": {"QUEUED", "FAILED", "CANCELLED"},
    "QUEUED": {"INITIALIZING", "FAILED", "CANCELLED"},
    "INITIALIZING": {"BROWSER_READY", "FAILED", "CANCELLED"},
    "BROWSER_READY": {"RUNNING", "FAILED", "CANCELLED"},
    "RUNNING": {"WAITING", "PAUSED", "HUMAN_CONTROLLED", "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "BLOCKED", "UNVERIFIED"},
    "WAITING": {"RUNNING", "PAUSED", "HUMAN_CONTROLLED", "FAILED", "TIMEOUT", "CANCELLED"},
    "PAUSED": {"HUMAN_CONTROLLED", "RESUMING", "CANCELLED", "FAILED"},
    "HUMAN_CONTROLLED": {"RESUMING", "CANCELLED", "FAILED"},
    "RESUMING": {"RUNNING", "OBSERVING", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "TIMEOUT": set(),
    "BLOCKED": set(),
    "NEEDS_INPUT": {"RUNNING", "FAILED", "CANCELLED"},
    "UNVERIFIED": set(),
}

TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "BLOCKED", "UNVERIFIED"}


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
