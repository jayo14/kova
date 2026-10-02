"""Execution-scoped agent memory.

Structured state that survives every planning/replanning cycle. Identity
(temporary email, password reference, auth state) lives HERE, never in model
context — the model is re-shown the relevant facts each turn; it is never
trusted to remember them.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class IdentityContext:
    """The single identity used for the entire execution (§9/§12 invariant).

    The temporary email is created once and reused for signup, forgot-password,
    and mailbox access. Never regenerated. Secrets are stored by reference into
    the deterministic CredentialStore, not inline.
    """

    email: str | None = None
    # Password values live only in the execution's CredentialStore; memory
    # holds the credential id + which phase it belongs to.
    password_credential_id: str | None = None
    new_password_credential_id: str | None = None
    mailbox_id: str | None = None
    account_created: bool = False
    account_verified: bool = False
    authenticated: bool = False
    logged_out: bool = False
    # Workflow lifecycle flags — updated ONLY by the executor from real
    # outcomes (never by the reasoner guessing):
    signup_completed: bool = False       # signup form submitted successfully
    recovery_requested: bool = False     # forgot-password form submitted
    reset_link_opened: bool = False      # reset link from email was opened
    password_reset: bool = False         # new password submitted successfully

    def to_safe_dict(self) -> dict:
        """Redacted view safe for events/UI/AI prompts (never secrets)."""
        return {
            "email": self.email,
            "mailbox_id": self.mailbox_id,
            "account_created": self.account_created,
            "account_verified": self.account_verified,
            "authenticated": self.authenticated,
            "logged_out": self.logged_out,
            "signup_completed": self.signup_completed,
            "recovery_requested": self.recovery_requested,
            "reset_link_opened": self.reset_link_opened,
            "password_reset": self.password_reset,
            "has_password_ref": self.password_credential_id is not None,
            "has_new_password_ref": self.new_password_credential_id is not None,
        }


@dataclass
class ObservedFact:
    """A deterministic fact the agent has established about the application."""

    kind: str            # e.g. "route", "control", "auth_state", "email"
    detail: str          # compact description, safe to show
    created_at: float = field(default_factory=time.time)


@dataclass
class ActionRecord:
    """Record of one executed action and its observed result."""

    step_index: int
    action: str
    description: str
    reason: str
    outcome: str         # "success" | "failed" | "verification_failed" | ...
    detail: str = ""
    url_after: str = ""
    created_at: float = field(default_factory=time.time)


class AgentMemory:
    """Short-term execution memory. Lives and dies with one execution."""

    def __init__(self, execution_id: uuid.UUID, objective: str = ""):
        self.execution_id = execution_id
        self.objective = objective
        self.identity = IdentityContext()
        self.facts: list[ObservedFact] = []
        self.actions: list[ActionRecord] = []
        self.completed_objectives: list[str] = []
        self.current_url: str = ""
        self.auth_state: str = "unknown"   # unknown | authenticated | logged_out
        self.replan_count: int = 0
        self.recovery_count: int = 0

    def add_fact(self, kind: str, detail: str) -> None:
        detail = detail.strip()[:300]
        if detail and not any(f.kind == kind and f.detail == detail for f in self.facts):
            self.facts.append(ObservedFact(kind=kind, detail=detail))
            # bounded memory: keep the most recent 50 facts
            if len(self.facts) > 50:
                self.facts = self.facts[-50:]

    def record_action(
        self,
        step_index: int,
        action: str,
        description: str,
        reason: str,
        outcome: str,
        detail: str = "",
        url_after: str = "",
    ) -> None:
        self.actions.append(ActionRecord(
            step_index=step_index,
            action=action,
            description=description,
            reason=reason,
            outcome=outcome,
            detail=detail[:300],
            url_after=url_after,
        ))
        if len(self.actions) > 100:
            self.actions = self.actions[-100:]

    def record_completion(self, objective: str) -> None:
        if objective not in self.completed_objectives:
            self.completed_objectives.append(objective)

    def compact_view(self) -> dict:
        """Compact structured memory for AI prompts (redacted, bounded)."""
        return {
            "objective": self.objective,
            "current_url": self.current_url,
            "auth_state": self.auth_state,
            "identity": self.identity.to_safe_dict(),
            "completed_objectives": self.completed_objectives,
            "key_facts": [f"{f.kind}: {f.detail}" for f in self.facts[-15:]],
            "recent_actions": [
                {
                    "action": a.action,
                    "description": a.description,
                    "outcome": a.outcome,
                    "url_after": a.url_after,
                }
                for a in self.actions[-8:]
            ],
            "replan_count": self.replan_count,
        }
