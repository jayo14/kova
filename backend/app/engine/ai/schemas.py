"""Structured output schemas for the AI agent layer.

Every AI capability returns one of these validated models. Raw model text never
becomes an executable action — these schemas are the only contract, and the
deterministic runtime validates them further before execution.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class GoalInterpretation(BaseModel):
    """Natural-language objective → structured executable intent."""

    goal: str = Field(description="Short canonical goal statement")
    domain: Literal[
        "authentication", "content", "ecommerce", "settings",
        "communication", "data_entry", "navigation", "unknown",
    ]
    intent: str = Field(description="Machine intent id, e.g. forgot_password, signup, search")
    success_requirements: list[str] = Field(
        default_factory=list,
        description="Observable outcomes that together prove the goal",
    )
    needs_account: bool = Field(
        default=False,
        description="True when the goal requires an account on the target app",
    )
    needs_email_capability: bool = Field(
        default=False,
        description="True when the goal may require receiving email (verification/reset)",
    )
    risk_level: Literal["low", "medium", "high"] = "low"
    reasoning: str = ""


class ProposedStep(BaseModel):
    """One step of an AI-proposed journey."""

    description: str = Field(description="Human-readable step description")
    action: Literal[
        "navigate", "click", "type", "clear", "select", "check", "uncheck",
        "wait", "press", "scroll", "create_email", "read_email", "extract_link",
        "observe",
    ]
    # Semantic target description — resolved by the deterministic runtime,
    # never executed raw. May carry candidate texts / role hints.
    target: dict[str, Any] = Field(default_factory=dict)
    value: str = ""                     # literal value (non-secret) if any
    credential_intent: Literal["none", "email", "password", "new_password"] = "none"
    expected_outcome: str = Field(default="", description="What should be true after this step")
    verification: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic verification condition dict (known Verifier keys only)",
    )


class JourneyPlan(BaseModel):
    """Intent + observations → structured journey."""

    objective: str
    intent: str
    steps: list[ProposedStep]
    success_condition: dict[str, Any] = Field(
        description="Final verification condition (known Verifier keys only)"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: Literal["low", "medium", "high"] = "low"
    evidence_requirements: list[str] = Field(default_factory=list)
    reasoning: str = ""


class ActionProposal(BaseModel):
    """A single next-action proposal from the agent loop."""

    action: Literal[
        "navigate", "click", "type", "clear", "select", "check", "uncheck",
        "wait", "press", "scroll", "create_email", "read_email", "extract_link",
        "observe", "request_human", "abort",
    ]
    target: dict[str, Any] = Field(default_factory=dict)
    value: str = ""
    credential_intent: Literal["none", "email", "password", "new_password"] = "none"
    reason: str = Field(description="Concise operational reason shown in the UI")
    expected_effect: str = ""
    verification: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class RecoveryProposal(BaseModel):
    """Proposal after a failure. Existing retry safety remains authoritative."""

    strategy: Literal[
        "retry_same", "alternative_target", "alternative_route",
        "observe_more", "request_human", "abort",
    ]
    alternative_target: dict[str, Any] = Field(default_factory=dict)
    reason: str
    action: ActionProposal | None = None


class VerificationProposal(BaseModel):
    """AI's semantic read of whether the objective was satisfied."""

    intent_satisfied: bool
    reason: str
    required_facts: list[str] = Field(
        default_factory=list,
        description="Deterministic facts that must be present to accept success",
    )
    suggested_condition: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional deterministic condition proposal (validated separately)",
    )


class EmailSelection(BaseModel):
    """AI's selection of the relevant message/link from a mailbox."""

    message_index: int = Field(ge=0, description="Index into the listed messages")
    reason: str = ""
    link_index: int = Field(default=0, ge=0, description="Index into the message's links")
