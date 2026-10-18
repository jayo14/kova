"""Execution context for tracking state during flow execution."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from typing import Any

from app.engine.credentials.store import CredentialStore
from app.engine.execution.state import ExecutionState, validate_transition


@dataclass
class PrerequisiteResult:
    """Record of a prerequisite flow execution result."""

    flow_id: str | None
    established_state: dict[str, Any]
    success: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Mutable context passed through execution.

    Tracks state, events, observations, credentials, and product state for a single execution.
    """

    execution_id: str
    target_url: str
    state: ExecutionState = ExecutionState.IDLE
    current_step_index: int = 0
    current_step_id: str | None = None
    observations: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    credentials: CredentialStore = field(default_factory=CredentialStore)
    current_state: dict[str, Any] = field(default_factory=dict)
    execution_plan: Any | None = None
    session_manager: Any | None = None
    prerequisite_results: list[PrerequisiteResult] = field(default_factory=list)
    persona: str = "default"
    app_host: str | None = None
    available_credentials: set[str] = field(default_factory=set)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    control_state: str = "agent"  # "agent" | "human" | "paused"
    project: Any | None = None
    execution_limits: Any | None = None
    safety_restrictions: Any | None = None
    browser_settings: Any | None = None
    _emitted_count: int = 0

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
            "current_state": self.current_state,
            "prerequisite_results": [
                {
                    "flow_id": r.flow_id,
                    "established_state": r.established_state,
                    "success": r.success,
                    "details": r.details,
                }
                for r in self.prerequisite_results
            ],
            "events": self.events,
            "observations": self.observations,
            "errors": self.errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
