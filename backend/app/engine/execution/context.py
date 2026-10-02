"""Execution context for tracking state during flow execution."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.engine.credentials.store import CredentialStore
from app.engine.execution.state import ExecutionState, validate_transition


@dataclass
class ExecutionContext:
    """Mutable context passed through execution.

    Tracks state, events, observations, and credentials for a single execution.
    """

    execution_id: str
    target_url: str
    state: ExecutionState = ExecutionState.IDLE
    current_step_index: int = 0
    observations: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    credentials: CredentialStore = field(default_factory=CredentialStore)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    control_state: str = "agent"  # "agent" | "human" | "paused"

    def transition(self, new_state: ExecutionState) -> None:
        """Transition to a new state with validation.

        Raises:
            InvalidTransitionError if transition is not allowed.
        """
        validate_transition(self.state.value, new_state.value)
        self.state = new_state

    def record_event(self, event_type: str, data: dict | None = None) -> None:
        """Record a timestamped event."""
        self.events.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "data": data or {},
            }
        )

    def record_observation(self, observation: dict) -> None:
        """Record a page observation."""
        self.observations.append(observation)

    def record_error(self, error: str) -> None:
        """Record an error message."""
        self.errors.append(error)

    def to_dict(self) -> dict:
        """Serialize context for persistence."""
        return {
            "execution_id": self.execution_id,
            "state": self.state.value,
            "current_step_index": self.current_step_index,
            "events": self.events,
            "observations": self.observations,
            "errors": self.errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
