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
    injection_detected: bool = False
    injection_evidence: str = ""


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


class CompiledExpectation(BaseModel):
    """Structured verification condition compiled from natural language."""

    condition: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic verification condition dict (known Verifier keys only)",
    )
    explanation: str = Field(
        default="",
        description="Reasoning or description of how the condition proves the outcome",
    )

    @classmethod
    def model_validate(cls, obj: Any, **kwargs) -> "CompiledExpectation":
        if isinstance(obj, dict):
            known = {
                "element_visible", "element_present", "text_visible", "text_present",
                "element_absent", "text_absent", "heading_changed", "url_matches",
                "url_changed_from", "url_changed_to", "element_enabled", "element_checked",
                "element_value", "page_loaded", "auth_verified", "element_count",
            }
            if "condition" in obj and isinstance(obj["condition"], dict):
                inner_known = {k: v for k, v in obj["condition"].items() if k in known}
                if inner_known:
                    return super().model_validate({
                        "condition": inner_known,
                        "explanation": str(obj.get("explanation", obj.get("reasoning", ""))),
                    }, **kwargs)
            known_in_data = {k: v for k, v in obj.items() if k in known}
            if known_in_data:
                return super().model_validate({
                    "condition": known_in_data,
                    "explanation": str(obj.get("explanation", obj.get("reasoning", ""))),
                }, **kwargs)
            return super().model_validate({
                "condition": {},
                "explanation": str(obj.get("explanation", obj.get("reasoning", ""))),
            }, **kwargs)
        return super().model_validate(obj, **kwargs)


class AIGeneratedJourney(BaseModel):
    """An intelligent, purpose-driven user journey synthesized by AI."""

    name: str = Field(description="Action-oriented journey name, e.g. 'Create and customize a study set'")
    title: str = Field(description="Short human-friendly title, e.g. 'Create Study Set'")
    description: str = Field(description="Clear explanation of the feature and what this journey validates")
    objective: str = Field(description="Verification objective proving the feature operates correctly")
    persona: str = Field(default="User", description="Persona executing this workflow")
    category: Literal["feature", "dashboard", "content", "settings", "workflow", "crud", "auth"] = "feature"
    journey: list[str] = Field(
        default_factory=list,
        description="Numbered or sequential high-level user actions",
    )
    steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Executable browser steps: navigate, click, fill/type, select, wait",
    )
    success_condition: dict[str, Any] = Field(
        default_factory=dict,
        description="Verification condition (text_visible, element_visible, url_changed_to, etc.)",
    )
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    recommended: bool = Field(default=False, description="True for the primary core product workflow")
    estimated_time_seconds: int = Field(default=25, ge=5, le=120)


class AIGeneratedJourneyList(BaseModel):
    """Collection of intelligent product journeys with editorial recommendation."""

    journeys: list[AIGeneratedJourney] = Field(default_factory=list)
    recommendation_reason: str = Field(
        default="",
        description="Editorial explanation of why the recommended journeys were selected",
    )


class AuthFormSemanticResult(BaseModel):
    """Semantic identification of authentication elements on arbitrary or non-standard DOMs."""

    email_or_user_index: int | None = Field(
        default=None,
        description="Index of candidate element corresponding to email, username, or identifier input",
    )
    password_index: int | None = Field(
        default=None,
        description="Index of candidate element corresponding to password input",
    )
    submit_index: int | None = Field(
        default=None,
        description="Index of candidate element corresponding to form submit, continue, or action button",
    )
    name_index: int | None = Field(
        default=None,
        description="Index of candidate element corresponding to full name or display name input (if registration)",
    )
    is_multi_step: bool = Field(
        default=False,
        description="True if the form only asks for email/username on current step before revealing password",
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = ""


class AuthEntranceSemanticResult(BaseModel):
    """Semantic identification of the navigation button/link to enter login or signup."""

    entrance_index: int | None = Field(
        default=None,
        description="Index of candidate link or button that navigates to or opens the signup/login modal or page",
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = ""


class AuthPageClassification(BaseModel):
    """Semantic classification of an authentication or gated web page."""

    kind: Literal[
        "login",
        "signup",
        "magic_link",
        "oauth_redirect",
        "otp_verification",
        "not_auth",
        "ambiguous",
    ]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    proposed_next_action: str | None = None
    reasoning: str = ""


class SubmitButtonProposal(BaseModel):
    """Proposal for form submit button selector."""

    selector: str | None = Field(default=None, description="CSS selector for submit button")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = ""


class ProposedFlowStep(BaseModel):
    action: str
    target: str = ""
    value: str = ""
    description: str = ""


class ProposedFlow(BaseModel):
    name: str
    steps: list[ProposedFlowStep] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = ""


class ProposedFlowList(BaseModel):
    flows: list[ProposedFlow] = Field(default_factory=list)


class FailureHypothesis(BaseModel):
    """AI-proposed failure hypothesis correlating assertions and evidence."""

    root_cause: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_cited: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    recommended_investigation: str
    reproduction_steps: list[str] = Field(default_factory=list)


class ReportSummary(BaseModel):
    """AI-synthesized human-readable report summary."""

    headline: str
    key_findings: list[str] = Field(default_factory=list)
    overall_assessment: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    recommended_next_steps: list[str] = Field(default_factory=list)


class ScenarioValidityAssessment(BaseModel):
    """AI-driven assessment of whether a test scenario remains valid after UI drift."""

    flow_id: str
    is_still_valid: bool
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    changes_detected: list[str] = Field(default_factory=list)
    acceptance_criteria_impacted: list[str] = Field(default_factory=list)
    requires_review: bool = False
    proposed_locator_updates: list[dict] = Field(default_factory=list)
    reasoning: str = ""





