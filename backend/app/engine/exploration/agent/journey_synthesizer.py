"""Synthesizes grounded, evidence-backed user journeys from ApplicationUnderstanding.

Ensures every generated user journey:
- Solves a real user-centric goal rather than clicking isolated elements.
- Rejects flimsy landing-page mockups, testimonials, and marketing cards.
- Carries explicit prerequisites, observed routes, and concrete success conditions.
- Distinguishes verified workflows (confirmed during exploration) from candidate capabilities.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.engine.exploration.agent.understanding import (
    ApplicationUnderstanding,
    EpistemicState,
    InvestigatedCapability,
)
from app.modules.exploration.journey_validator import is_flimsy_landing_element
from app.modules.exploration.schemas import DiscoveredMission

logger = logging.getLogger(__name__)


class JourneySynthesizer:
    """Transforms an ApplicationUnderstanding model into actionable DiscoveredMissions."""

    def __init__(self, understanding: ApplicationUnderstanding, app_name: str | None = None):
        self.understanding = understanding
        self.app_name = app_name or understanding.app_name or "Application"

    def synthesize_journeys(self) -> list[DiscoveredMission]:
        missions: list[DiscoveredMission] = []
        seen_names: set[str] = set()

        # 1. Synthesize from experimentally confirmed capabilities
        for cap in self.understanding.capabilities.values():
            if cap.state == EpistemicState.CONFIRMED:
                m = self._synthesize_confirmed_mission(cap)
                if m and m.name.lower() not in seen_names:
                    seen_names.add(m.name.lower())
                    missions.append(m)

        # 2. Synthesize from observed core capabilities (e.g. inside authenticated workspaces)
        for cap in self.understanding.capabilities.values():
            if cap.state in (EpistemicState.OBSERVED, EpistemicState.HYPOTHESIS):
                # Filter out flimsy landing-page controls, testimonials, and static cards
                if is_flimsy_landing_element(cap.name):
                    continue
                m = self._synthesize_observed_mission(cap)
                if m and m.name.lower() not in seen_names:
                    seen_names.add(m.name.lower())
                    missions.append(m)

        # 3. Add Authentication Journey if authentication was discovered
        if self.understanding.auth_required:
            auth_mission = self._synthesize_auth_mission()
            if auth_mission and auth_mission.name.lower() not in seen_names:
                seen_names.add(auth_mission.name.lower())
                missions.append(auth_mission)

        # 4. Rank and recommend primary user workflows
        self._rank_and_recommend(missions)
        return missions

    def _synthesize_confirmed_mission(self, cap: InvestigatedCapability) -> DiscoveredMission | None:
        name = f"Complete {cap.name}"
        journey_steps = [f"Open {self.app_name}"]

        for step in cap.observed_steps:
            action_type = step.get("action")
            target = step.get("target") or {}
            target_name = target.get("text") or target.get("name") or target.get("url") or "control"
            if action_type == "open_link":
                journey_steps.append(f"Navigate to {target_name}")
            elif action_type == "authenticate":
                journey_steps.append("Authenticate with user credentials")
            elif action_type == "fill_inputs":
                journey_steps.append("Fill required inputs")
            elif action_type == "submit_form":
                journey_steps.append("Submit form")
            else:
                journey_steps.append(f"Click '{target_name}'")

        outcome = cap.expected_outcome or f"Successfully completed {cap.name} workflow"
        journey_steps.append(f"Verify outcome: {outcome}")

        return DiscoveredMission(
            id=f"mission-conf-{uuid.uuid4().hex[:8]}",
            name=name,
            title=name,
            description=f"Experimentally confirmed workflow: {cap.user_goal or cap.name}",
            objective=cap.user_goal or f"Execute and verify {cap.name}",
            category="workflow",
            kind="end_to_end_journey",
            discovery_status="verified",
            validation_status="eligible",
            runnable=True,
            is_core=cap.is_core,
            confidence=0.95,
            expected_outcome=outcome,
            successCondition=outcome,
            prerequisites=cap.preconditions,
            journey=journey_steps,
            steps=[{"type": "confirmed_step", "capability_id": cap.id}],
            provenance={
                "source": "epistemic_agent_confirmation",
                "evidence": cap.evidence,
                "preconditions": cap.preconditions,
            },
        )

    def _synthesize_observed_mission(self, cap: InvestigatedCapability) -> DiscoveredMission | None:
        name = f"Use {cap.name}"
        user_goal = cap.user_goal or f"Access and use '{cap.name}'"
        outcome = cap.expected_outcome or f"Interface responds to '{cap.name}' and displays relevant content"

        journey_steps = [
            f"Open {self.app_name}",
            f"Locate and activate '{cap.name}'",
            f"Verify outcome: {outcome}",
        ]

        is_authenticated_precondition = "authenticated_session" in cap.preconditions
        has_access = self.understanding.is_currently_authenticated or self.understanding.auth_credentials_available
        runnable = not is_authenticated_precondition or has_access

        return DiscoveredMission(
            id=f"mission-obs-{uuid.uuid4().hex[:8]}",
            name=name,
            title=name,
            description=f"Application capability: {user_goal}",
            objective=user_goal,
            category="feature",
            kind="feature_test",
            discovery_status="discovered",
            validation_status="eligible" if runnable else "blocked_by_prerequisites",
            runnable=runnable,
            is_core=cap.is_core,
            confidence=0.85 if cap.is_core else 0.7,
            expected_outcome=outcome,
            successCondition=outcome,
            prerequisites=cap.preconditions,
            journey=journey_steps,
            steps=[{"type": "control_action", "control": cap.name}],
            rejection_reasons=["Requires authenticated session"] if not runnable else [],
            provenance={
                "source": "observed_capability",
                "preconditions": cap.preconditions,
            },
        )

    def _synthesize_auth_mission(self) -> DiscoveredMission | None:
        has_creds = self.understanding.auth_credentials_available
        has_signup = self.understanding.self_registration_available

        if has_creds:
            name = "Sign in to User Workspace"
            objective = "Log in with configured credentials and reach application workspace"
            outcome = "Authenticated workspace is loaded and session is established"
            steps = [
                f"Open {self.app_name}",
                "Navigate to login",
                "Enter configured credentials",
                "Submit login form",
                "Verify workspace loaded",
            ]
            runnable = True
            val_status = "eligible"
            reasons = []
        elif has_signup:
            name = "Register New Account"
            objective = "Sign up for an account to access application features"
            outcome = "New account created and onboarded into workspace"
            steps = [
                f"Open {self.app_name}",
                "Navigate to account registration",
                "Fill registration form",
                "Submit account creation",
                "Verify onboarding workspace loaded",
            ]
            runnable = True
            val_status = "eligible"
            reasons = []
        else:
            name = "Sign in to Account"
            objective = "Authenticate to access workspace"
            outcome = "Authenticated workspace is loaded"
            steps = [
                f"Open {self.app_name}",
                "Navigate to sign in",
                "Provide credentials",
                "Verify authenticated state",
            ]
            runnable = False
            val_status = "blocked_by_prerequisites"
            reasons = ["Authentication requires credentials"]

        return DiscoveredMission(
            id=f"mission-auth-{uuid.uuid4().hex[:8]}",
            name=name,
            title=name,
            description=objective,
            objective=objective,
            category="auth",
            kind="feature_test",
            discovery_status="discovered",
            validation_status=val_status,
            runnable=runnable,
            is_core=True,
            confidence=0.9 if runnable else 0.5,
            expected_outcome=outcome,
            successCondition=outcome,
            prerequisites=["valid_credentials"] if not has_signup else [],
            rejection_reasons=reasons,
            journey=steps,
            provenance={
                "source": "auth_investigation",
                "auth_type": self.understanding.auth_type,
            },
        )

    def _rank_and_recommend(self, missions: list[DiscoveredMission]) -> None:
        """Sort and mark top high-value missions as recommended."""
        missions.sort(
            key=lambda m: (
                1 if m.discovery_status == "verified" else 0,
                1 if m.is_core else 0,
                1 if m.runnable else 0,
                m.confidence or 0.0,
            ),
            reverse=True,
        )

        recommended_count = 0
        for m in missions:
            if m.runnable and (m.discovery_status == "verified" or m.is_core):
                if recommended_count < 3:
                    m.recommended = True
                    recommended_count += 1
