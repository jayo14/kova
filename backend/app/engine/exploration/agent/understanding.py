"""Epistemic application understanding model for autonomous exploration.

Maintains an evolving, structured model of the target application throughout
the investigation. Distinguishes direct observations, hypotheses, and
experimentally confirmed behavior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class EpistemicState(str, Enum):
    """Epistemic state of an application belief or capability."""
    HYPOTHESIS = "hypothesis"            # Inferred from text, context, or common patterns; not yet verified
    OBSERVED = "observed"                # Directly observed on page (UI control, form, link, or route)
    CONFIRMED = "confirmed"              # Experimentally confirmed via browser action and resulting state change
    BLOCKED = "blocked"                  # Attempted but blocked (e.g. auth required, verification needed, permissions)
    REFUTED = "refuted"                  # Hypothesis disproved by interaction outcome


class SessionAuthState(str, Enum):
    """Reliable session authentication state model."""
    AUTHENTICATION_PENDING = "authentication_pending"
    AUTHENTICATION_IN_PROGRESS = "authentication_in_progress"
    AUTHENTICATION_SUCCESSFUL = "authentication_successful"
    AUTHENTICATED_SESSION_MAINTAINED = "authenticated_session_maintained"
    AUTHENTICATION_GENUINELY_LOST = "authentication_genuinely_lost"
    AUTHENTICATION_STATE_UNCERTAIN = "authentication_state_uncertain"


class ProvenanceSource(str, Enum):
    """Source of an observation or belief."""
    INITIAL_SCAN = "initial_scan"
    DOM_OBSERVATION = "dom_observation"
    INTERACTION_RESULT = "interaction_result"
    AI_REASONING = "ai_reasoning"
    AUTHENTICATION_FLOW = "authentication_flow"


class ApplicationArea(BaseModel):
    """A distinct structural or functional zone within the application."""
    id: str = Field(default_factory=lambda: f"area-{uuid.uuid4().hex[:8]}")
    name: str                            # e.g. "Public Landing", "Sign In / Registration", "User Workspace", "Report Studio"
    path_pattern: str                    # e.g. "/", "/register", "/dashboard", "/app/projects/*"
    is_authenticated: bool = False
    discovered_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence_urls: list[str] = Field(default_factory=list)
    key_controls: list[str] = Field(default_factory=list)
    description: str = ""

    model_config = ConfigDict(extra="ignore")


class InvestigatedCapability(BaseModel):
    """An established or hypothesized application capability."""
    id: str = Field(default_factory=lambda: f"cap-{uuid.uuid4().hex[:8]}")
    name: str                            # Human-readable capability name
    description: str = ""
    user_goal: str = ""                  # What does the user achieve with this?
    user_persona: str = "User"           # Target user type
    state: EpistemicState = EpistemicState.HYPOTHESIS
    area_id: str | None = None
    entry_url: str = ""
    preconditions: list[str] = Field(default_factory=list)      # e.g. ["authenticated_session", "existing_project"]
    input_requirements: list[dict[str, Any]] = Field(default_factory=list)
    observed_steps: list[dict[str, Any]] = Field(default_factory=list)
    expected_outcome: str = ""           # What state transition or artifact proves success
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    is_core: bool = False                # Does this test the application's primary value proposition?

    model_config = ConfigDict(extra="ignore")


class StateTransition(BaseModel):
    """An experimentally confirmed transition between application states."""
    id: str = Field(default_factory=lambda: f"trans-{uuid.uuid4().hex[:8]}")
    from_url: str
    action_taken: dict[str, Any]
    to_url: str
    observed_effect: str                 # e.g. "Created new logbook entry and redirected to overview"
    artifact_created: str | None = None  # e.g. "report_id=123", "session_token"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    model_config = ConfigDict(extra="ignore")


class InvestigationQuestion(BaseModel):
    """An open epistemic unknown that guides subsequent actions."""
    id: str = Field(default_factory=lambda: f"q-{uuid.uuid4().hex[:8]}")
    question: str                        # e.g. "Can a visitor register without admin invitation?"
    hypothesis: str                      # e.g. "Public self-registration creates an active workspace"
    proposed_investigation: str          # e.g. "Fill registration form with synthetic test inputs"
    priority: int = 1                    # Higher number = higher priority
    status: Literal["open", "investigating", "answered", "abandoned"] = "open"
    answer: str | None = None

    model_config = ConfigDict(extra="ignore")


class DependencyState(BaseModel):
    """Tracks infrastructure and backend service readiness across time."""
    host: str
    kind: str = "backend"                # "backend", "auth_provider", "database"
    is_ready: bool = True
    last_status: str = "ready"           # "ready", "warming_up", "pending_request", "failed"
    pending_since: float | None = None
    pending_duration_s: float = 0.0
    failure_count: int = 0
    last_observed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    model_config = ConfigDict(extra="ignore")


class InterruptionRecord(BaseModel):
    """Tracks an encountered and investigated interface obstruction."""
    id: str = Field(default_factory=lambda: f"int-{uuid.uuid4().hex[:8]}")
    title: str = ""
    interruption_type: str = ""          # "optional_prompt", "required_setup", "permission_request", etc.
    decision: str = ""                   # "dismiss", "complete_required", "make_informed_choice", etc.
    resolution_action: str = ""
    resolved: bool = False
    underlying_workspace_accessible: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    model_config = ConfigDict(extra="ignore")


class ApplicationUnderstanding(BaseModel):
    """Living, evolving epistemic model of the target web application.

    Updated iteratively as the exploration agent observes, reasons, acts,
    and learns from interaction outcomes.
    """
    model_config = ConfigDict(extra="ignore")

    app_name: str = ""
    identity_and_purpose: str = ""
    target_url: str = ""
    likely_personas: list[str] = Field(default_factory=list)

    # Structural understanding
    areas: dict[str, ApplicationArea] = Field(default_factory=dict)
    known_routes: set[str] = Field(default_factory=set)

    # Functional understanding
    capabilities: dict[str, InvestigatedCapability] = Field(default_factory=dict)
    state_transitions: list[StateTransition] = Field(default_factory=list)
    discovered_objects: list[str] = Field(default_factory=list)  # e.g. ["Project", "Logbook", "Report", "Quiz"]

    # Authentication & access understanding
    auth_required: bool = False
    auth_type: str | None = None         # "password_form", "oauth", "magic_link", "none"
    self_registration_available: bool | None = None
    auth_credentials_available: bool = False
    is_currently_authenticated: bool = False
    session_state: SessionAuthState = SessionAuthState.AUTHENTICATION_STATE_UNCERTAIN
    auth_blockers: list[str] = Field(default_factory=list)       # e.g. ["EMAIL_VERIFICATION", "CAPTCHA"]
    auth_blocked: bool = False
    auth_blocker_reason: str = ""
    discovered_auth_methods: list[dict[str, Any]] = Field(default_factory=list)
    selected_auth_strategy: str | None = None
    attempted_auth_strategies: list[dict[str, Any]] = Field(default_factory=list)

    # Single-identity lifecycle: one exploration account per application per mission
    exploration_identity: dict[str, Any] | None = None  # {"email": ..., "password": ..., "name": ...}
    registration_submitted: bool = False  # True once native registration form has been submitted
    registration_outcome: str = "not_attempted"  # "not_attempted", "submitted_pending", "succeeded", "failed_validation", "failed_duplicate"

    # Infrastructure & dependency tracking
    dependencies: dict[str, DependencyState] = Field(default_factory=dict)

    # Interface interruptions handled
    interruptions: list[InterruptionRecord] = Field(default_factory=list)

    # Epistemic frontier
    open_questions: list[InvestigationQuestion] = Field(default_factory=list)
    investigation_log: list[dict[str, Any]] = Field(default_factory=list)

    def record_area(self, name: str, path_pattern: str, is_authenticated: bool = False, url: str = "") -> ApplicationArea:
        for area in self.areas.values():
            if area.name.lower() == name.lower() or area.path_pattern == path_pattern:
                if url and url not in area.evidence_urls:
                    area.evidence_urls.append(url)
                return area
        area = ApplicationArea(
            name=name,
            path_pattern=path_pattern,
            is_authenticated=is_authenticated,
            evidence_urls=[url] if url else [],
        )
        self.areas[area.id] = area
        return area

    def record_capability(
        self,
        name: str,
        user_goal: str = "",
        state: EpistemicState = EpistemicState.HYPOTHESIS,
        is_core: bool = False,
        expected_outcome: str = "",
        entry_url: str = "",
        preconditions: list[str] | None = None,
    ) -> InvestigatedCapability:
        # Check if already tracked by normalized name
        norm_name = name.lower().strip()
        for cap in self.capabilities.values():
            if cap.name.lower().strip() == norm_name:
                if state == EpistemicState.CONFIRMED or (state == EpistemicState.OBSERVED and cap.state == EpistemicState.HYPOTHESIS):
                    cap.state = state
                if user_goal and not cap.user_goal:
                    cap.user_goal = user_goal
                if expected_outcome:
                    cap.expected_outcome = expected_outcome
                if is_core:
                    cap.is_core = True
                return cap

        cap = InvestigatedCapability(
            name=name,
            user_goal=user_goal,
            state=state,
            is_core=is_core,
            expected_outcome=expected_outcome,
            entry_url=entry_url,
            preconditions=preconditions or [],
        )
        self.capabilities[cap.id] = cap
        return cap

    def confirm_capability(self, name_or_id: str, action: dict[str, Any], outcome: str) -> None:
        target = self.capabilities.get(name_or_id)
        if not target:
            for cap in self.capabilities.values():
                if cap.name.lower() == name_or_id.lower():
                    target = cap
                    break
        if not target:
            target = self.record_capability(
                name=name_or_id,
                user_goal=f"Execute {name_or_id}",
                state=EpistemicState.CONFIRMED,
                expected_outcome=outcome,
            )
        if target:
            target.state = EpistemicState.CONFIRMED
            target.confidence = 0.95
            target.observed_steps.append(action)
            target.expected_outcome = outcome
            target.evidence.append({
                "type": "experimental_confirmation",
                "action": action,
                "outcome": outcome,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def record_transition(self, from_url: str, action: dict[str, Any], to_url: str, effect: str, artifact: str | None = None) -> StateTransition:
        transition = StateTransition(
            from_url=from_url,
            action_taken=action,
            to_url=to_url,
            observed_effect=effect,
            artifact_created=artifact,
        )
        self.state_transitions.append(transition)
        return transition

    def add_question(self, question: str, hypothesis: str, proposed_investigation: str, priority: int = 1) -> InvestigationQuestion:
        # Avoid duplicate open questions
        for q in self.open_questions:
            if q.status == "open" and q.question.lower() == question.lower():
                return q
        q = InvestigationQuestion(
            question=question,
            hypothesis=hypothesis,
            proposed_investigation=proposed_investigation,
            priority=priority,
        )
        self.open_questions.append(q)
        return q

    def answer_question(self, question_text: str, answer: str) -> None:
        for q in self.open_questions:
            if q.question.lower() == question_text.lower() or question_text.lower() in q.question.lower():
                q.status = "answered"
                q.answer = answer
                break

    def record_auth_method(
        self,
        method_type: str,
        provider: str | None = None,
        label: str = "",
        entry_selector: str | None = None,
        entry_url: str | None = None,
        viable: bool = True,
    ) -> None:
        key = f"{method_type}:{provider or 'native'}"
        for m in self.discovered_auth_methods:
            if f"{m.get('type')}:{m.get('provider') or 'native'}" == key:
                if entry_selector and not m.get("entry_selector"):
                    m["entry_selector"] = entry_selector
                if entry_url and not m.get("entry_url"):
                    m["entry_url"] = entry_url
                if label and not m.get("label"):
                    m["label"] = label
                return
        self.discovered_auth_methods.append({
            "type": method_type,
            "provider": provider,
            "label": label or (f"{provider} OAuth" if provider else method_type),
            "viable": viable,
            "attempted": False,
            "outcome": None,
            "entry_selector": entry_selector,
            "entry_url": entry_url,
        })

    def record_auth_attempt(
        self,
        method_type: str,
        provider: str | None = None,
        success: bool = False,
        outcome: str = "",
    ) -> None:
        key = f"{method_type}:{provider or 'native'}"
        self.attempted_auth_strategies.append({
            "type": method_type,
            "provider": provider,
            "success": success,
            "outcome": outcome,
        })
        for m in self.discovered_auth_methods:
            if f"{m.get('type')}:{m.get('provider') or 'native'}" == key:
                m["attempted"] = True
                m["outcome"] = outcome
                if not success:
                    m["viable"] = False
                return

    def set_exploration_identity(self, email: str, password: str, name: str = "Kova Tester") -> None:
        """Set the single exploration identity for this mission. Called once during first registration."""
        if self.exploration_identity is None:
            self.exploration_identity = {"email": email, "password": password, "name": name}

    def get_exploration_credentials(self) -> dict[str, Any] | None:
        """Return the exploration identity credentials if one has been established."""
        return self.exploration_identity

    def mark_registration_submitted(self) -> None:
        """Mark that native registration has been submitted for the exploration identity."""
        self.registration_submitted = True
        self.registration_outcome = "submitted_pending"

    def mark_registration_succeeded(self) -> None:
        """Mark that the registration was confirmed successful (session granted)."""
        self.registration_outcome = "succeeded"

    def mark_registration_failed(self, reason: str = "failed_validation") -> None:
        """Mark registration as failed with a specific reason."""
        self.registration_outcome = reason

    def mark_auth_blocked(self, reason: str) -> None:
        self.auth_blocked = True
        self.auth_blocker_reason = reason
        if reason not in self.auth_blockers:
            self.auth_blockers.append(reason)

    def has_active_identity(self) -> bool:
        """Return True if an exploration identity has been created (regardless of auth success)."""
        return self.exploration_identity is not None

    def should_attempt_login_instead(self) -> bool:
        """Return True if registration was already attempted and we should try login with existing credentials."""
        return (
            self.registration_submitted
            and self.exploration_identity is not None
            and not self.is_currently_authenticated
            and self.registration_outcome in ("submitted_pending", "succeeded", "failed_duplicate")
        )

    def update_session_auth(self, new_state: SessionAuthState, reason: str = "") -> None:
        self.session_state = new_state
        if new_state in (SessionAuthState.AUTHENTICATION_SUCCESSFUL, SessionAuthState.AUTHENTICATED_SESSION_MAINTAINED):
            self.is_currently_authenticated = True
        elif new_state == SessionAuthState.AUTHENTICATION_GENUINELY_LOST:
            self.is_currently_authenticated = False

    def update_dependency(
        self,
        host: str,
        is_ready: bool,
        status: str = "ready",
        pending_duration: float = 0.0,
        kind: str = "backend",
    ) -> DependencyState:
        dep = self.dependencies.get(host)
        if not dep:
            dep = DependencyState(
                host=host,
                kind=kind,
                is_ready=is_ready,
                last_status=status,
                pending_duration_s=pending_duration,
            )
            self.dependencies[host] = dep
        else:
            dep.is_ready = is_ready
            dep.last_status = status
            dep.pending_duration_s = pending_duration
            dep.last_observed_at = datetime.now(timezone.utc).isoformat()
            if not is_ready:
                dep.failure_count += 1
        return dep

    def is_dependency_ready(self, host: str | None = None) -> bool:
        if host:
            dep = self.dependencies.get(host)
            return dep.is_ready if dep else True
        return all(d.is_ready for d in self.dependencies.values())

    def record_interruption(
        self,
        title: str,
        interruption_type: str,
        decision: str,
        resolution_action: str = "",
        resolved: bool = True,
        underlying_accessible: bool = True,
    ) -> InterruptionRecord:
        record = InterruptionRecord(
            title=title,
            interruption_type=interruption_type,
            decision=decision,
            resolution_action=resolution_action,
            resolved=resolved,
            underlying_workspace_accessible=underlying_accessible,
        )
        self.interruptions.append(record)
        return record

    def get_confirmed_capabilities(self) -> list[InvestigatedCapability]:
        return [c for c in self.capabilities.values() if c.state == EpistemicState.CONFIRMED]

    def summarize_understanding(self) -> dict[str, Any]:
        """Produce an actionable summary for reasoning and journey generation."""
        return {
            "app_name": self.app_name,
            "purpose": self.identity_and_purpose,
            "personas": self.likely_personas,
            "is_authenticated": self.is_currently_authenticated,
            "auth_strategy": self.selected_auth_strategy,
            "discovered_auth_methods": [
                {"type": m.get("type"), "provider": m.get("provider"), "viable": m.get("viable"), "attempted": m.get("attempted")}
                for m in self.discovered_auth_methods
            ],
            "areas_count": len(self.areas),
            "areas": [{"name": a.name, "authenticated": a.is_authenticated, "path": a.path_pattern} for a in self.areas.values()],
            "confirmed_capabilities": [
                {
                    "name": c.name,
                    "goal": c.user_goal,
                    "outcome": c.expected_outcome,
                    "is_core": c.is_core,
                    "preconditions": c.preconditions,
                }
                for c in self.capabilities.values()
                if c.state == EpistemicState.CONFIRMED
            ],
            "hypothesized_capabilities": [
                {"name": c.name, "goal": c.user_goal, "state": c.state.value}
                for c in self.capabilities.values()
                if c.state in (EpistemicState.HYPOTHESIS, EpistemicState.OBSERVED)
            ],
            "transitions_count": len(self.state_transitions),
            "open_questions": [q.question for q in self.open_questions if q.status == "open"],
            "blockers": self.auth_blockers,
            "session_state": self.session_state.value if hasattr(self.session_state, "value") else str(self.session_state),
            "has_exploration_identity": self.has_active_identity(),
            "registration_submitted": self.registration_submitted,
            "registration_outcome": self.registration_outcome,
            "dependencies": {
                h: {"ready": d.is_ready, "status": d.last_status, "pending_s": d.pending_duration_s}
                for h, d in self.dependencies.items()
            },
            "interruptions_handled": [
                {"title": r.title, "type": r.interruption_type, "decision": r.decision, "resolved": r.resolved}
                for r in self.interruptions
            ],
        }
