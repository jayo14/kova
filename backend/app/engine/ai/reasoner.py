"""Agent reasoning capabilities over the AI provider abstraction.

Each capability degrades gracefully: when AI is unavailable, deterministic
heuristics return conservative structured results so the agent loop can still
run (with reduced semantic adaptivity). AI output is ALWAYS a proposal — the
agent executor validates and executes it through the deterministic runtime.

Cost discipline (spec §27): AI is called only at semantic decision points —
goal interpretation, journey planning, next-action selection, recovery, and
final verification — never per DOM node.
"""

from __future__ import annotations

import json
import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.engine.ai.memory import AgentMemory
from app.engine.ai.observation import build_semantic_observation
from app.engine.ai.prompt_sanitizer import build_system_prompt_clause, taint_page_content
from app.engine.ai.provider import AIProvider, AIProviderError
from app.engine.ai.schemas import (
    ActionProposal,
    AIGeneratedJourney,
    AIGeneratedJourneyList,
    AuthEntranceSemanticResult,
    AuthFormSemanticResult,
    AuthPageClassification,
    FailureHypothesis,
    GoalInterpretation,
    JourneyPlan,
    ProposedFlowList,
    ProposedStep,
    RecoveryProposal,
    ReportSummary,
    ScenarioValidityAssessment,
    SubmitButtonProposal,
    VerificationProposal,
)

logger = logging.getLogger(__name__)

# Keywords that mark semantic equivalence classes for auth recovery (§7/§14).
RECOVERY_TEXTS = (
    "forgot password", "forgot your password", "reset password",
    "recover account", "password recovery", "can't sign in",
    "cannot sign in", "reset your password", "trouble signing in",
    "can't access your account", "can't access", "cant access",
    "recover", "recovery", "trouble accessing", "forgotten password",
    "lost password", "account recovery", "need help signing in",
)
VERIFICATION_EMAIL_TEXTS = (
    "verify your email", "confirm your account", "activate account",
    "verify email", "email verification", "confirm your email",
)
RESET_SENT_TEXTS = (
    # Reset-specific phrasings only — generic "check your email" collides
    # with signup verification prompts and must NOT trigger recovery state.
    "check your inbox", "recovery instructions have been", "recovery instructions sent",
    "if an account exists", "if that account exists", "password reset email", "reset email sent",
    "recovery email sent", "password reset was requested", "reset was requested",
    "we've sent a reset", "we have sent a reset", "sent a password reset",
    "instructions to reset your password", "sent instructions", "email with instructions",
    "recovery link sent", "recovery email has been sent",
)
SIGNUP_TEXTS = (
    "sign up", "signup", "create account", "register", "registration",
    "join", "get started", "start now", "new account", "create profile",
    "open account", "join the service",
)
LOGIN_TEXTS = (
    "log in", "login", "sign in", "signin", "member login",
    "access your account", "access", "portal", "continue to sign in",
)
LOGOUT_TEXTS = (
    "sign out", "sign-out", "log out", "log-out", "logout", "leave", "exit",
)


class AgentReasoner:
    """Semantic reasoning over compact observations. Proposals only."""

    def __init__(self, provider: AIProvider | None):
        self.provider = provider
        self._provider = provider

    # ── Phase 5: Goal interpretation ────────────────────────────────

    async def interpret_goal(self, objective: str) -> GoalInterpretation:
        if self.provider:
            system = (
                "You interpret software-testing objectives into structured intent. "
                "Respond ONLY with JSON matching the requested schema. Be conservative: "
                "set needs_account/needs_email_capability true whenever plausibly required."
                + build_system_prompt_clause()
            )
            prompt = (
                "Objective: "
                + objective
                + "\n\nReturn JSON: {goal, domain, intent, success_requirements[], "
                "needs_account, needs_email_capability, risk_level, reasoning}. "
                "domain ∈ authentication|content|ecommerce|settings|communication|"
                "data_entry|navigation|unknown. risk_level ∈ low|medium|high."
            )
            try:
                return await self.provider.generate_structured(system, prompt, GoalInterpretation)
            except AIProviderError as e:
                logger.warning("Goal interpretation via AI failed, using heuristics: %s", e)
        return self._heuristic_goal(objective)

    def _heuristic_goal(self, objective: str) -> GoalInterpretation:
        lower = objective.lower()
        intent = "unknown"
        domain = "unknown"
        needs_account = False
        needs_email = False
        requirements: list[str] = []

        is_recovery = (
            any(kw in lower for kw in (
                "forgot password", "forgotten", "password recovery", "reset password",
                "password reset", "recover their account password", "recover account",
                "recover password", "account recovery", "trouble signing in",
            ))
            or ("recover" in lower and "password" in lower)
            or ("reset" in lower and "password" in lower)
        )
        if is_recovery:
            intent = "forgot_password"
            domain = "authentication"
            has_explicit_email = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", lower))
            needs_account = not has_explicit_email
            needs_email = True
            requirements = [
                "password recovery can be initiated",
                "recovery email can be received",
                "recovery link can be opened",
                "password can be changed",
                "resulting authentication state is valid",
            ]
        elif any(kw in lower for kw in ("sign up", "signup", "register", "create account")):
            intent = "signup"
            domain = "authentication"
            needs_account = True
            requirements = ["account can be created", "resulting state reflects the new account"]
        elif any(kw in lower for kw in ("log in", "login", "sign in")):
            intent = "login"
            domain = "authentication"
            needs_account = True
            requirements = ["authentication succeeds", "authenticated state is reached"]
        elif "search" in lower:
            intent = "search"
            domain = "content"
            requirements = ["a results state appears"]
        else:
            intent = "explore"
            domain = "navigation"
            requirements = ["application responds to the requested interaction"]

        # Generic escalation: creating accounts usually wants email capability
        if any(kw in lower for kw in ("temporary email", "temp email", "create one", "if the account does not exist")):
            needs_account = True
            needs_email = True

        return GoalInterpretation(
            goal=objective[:120],
            domain=domain,
            intent=intent,
            success_requirements=requirements,
            needs_account=needs_account,
            needs_email_capability=needs_email,
            risk_level="medium" if intent == "forgot_password" else "low",
            reasoning="deterministic keyword interpretation",
        )

    # ── Phase 6: Journey planning ───────────────────────────────────

    async def plan_journey(
        self,
        memory: AgentMemory,
        interpretation: GoalInterpretation,
        observation: dict,
        has_email_provider: bool,
    ) -> JourneyPlan:
        semantic_view = build_semantic_observation(observation)
        if self.provider:
            system = (
                "You plan user journeys for browser automation. Output ONLY JSON. "
                "Steps must use only these actions: navigate, click, type, clear, select, "
                "check, uncheck, wait, press, scroll, create_email, read_email, extract_link, "
                "observe. Verification conditions must use only known keys: element_visible, "
                "element_absent, element_count, text_visible, text_absent, heading_changed, "
                "url_matches, url_changed_from, url_changed_to, element_enabled, "
                "element_checked, element_value, page_loaded, auth_verified. Never include "
                "passwords or secrets in any field — reference credentials via "
                "credential_intent instead."
                + build_system_prompt_clause()
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Structured intent: " + json.dumps(interpretation.model_dump()) + "\n"
                "Current observation:\n" + taint_page_content(json.dumps(semantic_view)) + "\n"
                "Email capability available: " + str(has_email_provider) + "\n"
                "Identity state: " + json.dumps(memory.identity.to_safe_dict()) + "\n\n"
                "Return JSON: {objective, intent, steps[{description, action, target, value, "
                "credential_intent, expected_outcome, verification}], success_condition, "
                "confidence, risk_level, evidence_requirements[], reasoning}."
            )
            try:
                return await self.provider.generate_structured(system, prompt, JourneyPlan)
            except AIProviderError as e:
                logger.warning("Journey planning via AI failed, using template: %s", e)
        return self._heuristic_plan(memory, interpretation, semantic_view, has_email_provider)

    def _heuristic_plan(
        self,
        memory: AgentMemory,
        interpretation: GoalInterpretation,
        observation: dict,
        has_email_provider: bool,
    ) -> JourneyPlan:
        """Conservative deterministic plan when AI is unavailable.

        Produces an observe-driven skeleton: the agent loop (Phase 7) refines
        it action-by-action using per-turn proposals, so the skeleton only
        needs the entry point.
        """
        steps = [ProposedStep(
            description="Open the application and observe its current state",
            action="navigate",
            target={},
            value=observation.get("url", ""),
            expected_outcome="Application home/auth page is displayed",
            verification={"page_loaded": True},
        )]
        return JourneyPlan(
            objective=memory.objective,
            intent=interpretation.intent,
            steps=steps,
            success_condition={"page_loaded": True},
            confidence=0.3,
            risk_level="low",
            evidence_requirements=["screenshots at each milestone"],
            reasoning="deterministic skeleton plan (AI unavailable); refined per-turn",
        )

    # ── Intelligent Exploration Journey Synthesis ───────────────────

    async def synthesize_journeys(
        self,
        base_url: str,
        title: str,
        goal: str | None,
        persona: str,
        routes: list[dict] | None = None,
        interactive_elements: list[dict] | None = None,
        page_summary: str = "",
        max_journeys: int = 5,
        time_budget_seconds: float = 30.0,
        site_map: list[dict] | None = None,
        capabilities: list[dict] | None = None,
    ) -> AIGeneratedJourneyList | None:
        """Synthesize intelligent, purposeful user journeys grounded in observed SiteMap + capabilities.

        Journeys are goals, not scripts: they declare an objective, preconditions, a concrete
        observable outcome, and a risk level. Steps never invent CSS selectors; they reference
        observed control labels (control_hints) that the executor resolves at run time.
        """
        if not self.provider:
            return None

        # Compact representation of observed page states (SiteMap nodes): forms with fields,
        # primary actions, and interactive controls. Chunk if needed to stay within budget.
        compact_states = []
        for node in (site_map or [])[:40]:
            forms_summary = []
            for f in (node.get("forms") or [])[:6]:
                fields = []
                for field in (f.get("fields") or f.get("inputs") or [])[:8]:
                    fields.append({
                        "name": field.get("name") or field.get("label") or "",
                        "type": field.get("type", "text"),
                    })
                forms_summary.append({
                    "action": f.get("action") or f.get("id") or "",
                    "method": f.get("method", ""),
                    "fields": fields,
                })
            actions_summary = [
                {
                    "label": a.get("name") or a.get("text") or "",
                    "type": a.get("type") or a.get("role") or "",
                }
                for a in (node.get("primary_actions") or [])[:10]
            ]
            controls_summary = [
                {
                    "label": el.get("name") or el.get("text") or "",
                    "type": el.get("type") or el.get("role") or "",
                }
                for el in (node.get("interactive_elements") or [])[:15]
            ]
            compact_states.append({
                "url": node.get("url") or node.get("url_norm") or "",
                "title": node.get("title"),
                "needs_auth": bool(node.get("needs_auth")),
                "forms": forms_summary,
                "primary_actions": actions_summary,
                "controls": controls_summary,
            })

        compact_routes = [
            {
                "path": r.get("path"),
                "title": r.get("title") or r.get("text"),
                "category": r.get("category"),
                "requires_auth": r.get("requires_auth", False),
            }
            for r in (routes or [])[:20]
            if r.get("path")
        ]

        compact_capabilities = [
            {
                "name": c.get("name"),
                "kind": c.get("kind"),
                "url": c.get("url"),
                "entry_point": c.get("entry_point"),
                "inputs": [i.get("name") or i.get("label") or "" for i in (c.get("inputs") or [])[:8]],
                "expected_outcome": c.get("expected_outcome"),
                "confidence": c.get("confidence"),
            }
            for c in (capabilities or [])[:40]
        ]

        system = (
            "You are an expert QA and product automation architect. Synthesize HIGH-VALUE, "
            "PURPOSEFUL user journeys that test real features of the web application.\\n\\n"
            "GROUNDING RULES (non-negotiable):\\n"
            "1. BASE EVERY JOURNEY ON OBSERVED EVIDENCE ONLY: use the page states, forms with "
            "their fields, primary actions, controls, routes, and discovered capabilities "
            "provided below. Never invent pages, controls, or domain concepts not observed.\\n"
            "2. JOURNEYS ARE GOALS, NOT SCRIPTS: each journey declares an objective, preconditions\\n"
            "(needs_login? needs_data?), a concrete observable expected outcome, a risk level,\\n"
            "and evidence refs. Do NOT ask the model to invent CSS selectors; steps reference\\n"
            "observed control labels (control_hints) that the executor resolves at run time.\\n"
            "3. NO PRODUCT-SPECIFIC KEYWORDS OR EXAMPLES: do not reference any particular product, brand, or feature name.\\n"
            "Logic must work for any site. Infer features purely from observed forms, inputs, actions, and content.\\n"
            "for any site. Infer features purely from observed forms, inputs, actions, and content.\\n"
            "4. CLASSIFICATION HONESTY: assign each journey a kind — smoke (page loads), navigation,\\n"
            "read workflow, or write workflow. A journey may only be titled or described as a\\n"
            "workflow if its steps and success condition actually exercise one. A navigation-only\\n"
            "mission must be titled as such (e.g. 'Open X', 'Browse X'), never 'Create X' unless\\n"
            "it actually submits and proves a persisted/visible result.\\n"
            "5. CONCRETE OUTCOMES: expected outcomes and success conditions must NEVER be vague\\n"
            "(never 'Verify visible feedback', 'Verify page loaded', 'Expected results present').\\n"
            "State precisely what concrete data, record, document, calculation, or status is expected.\\n"
            "6. AUTH AS A PREREQUISITE: treat auth as a prerequisite unless the user goal explicitly\\n"
            "requests testing authentication. Do not include auth steps in feature workflows.\\n"
            "7. STEPS: use only these actions — navigate, click, fill, select, wait. Targets must be\\n"
            "control labels from control_hints, never CSS selectors.\\n"
            "8. Output ONLY JSON matching the AIGeneratedJourneyList schema.\\n"
        )

        user_prompt = (
            f"Application URL: {base_url}\\n"
            f"Page Title: {title}\\n"
            f"Primary Persona: {persona}\\n"
            f"User Goal: {goal or 'Thoroughly test core application features'}\\n"
            f"Time budget: {time_budget_seconds:.0f}s\\n\\n"
            f"Observed Page States (SiteMap nodes):\\n{json.dumps(compact_states, indent=1)}\\n\\n"
            f"Discovered Routes:\\n{json.dumps(compact_routes, indent=1)}\\n\\n"
            f"Discovered Capabilities (from exploration):\\n{json.dumps(compact_capabilities, indent=1)}\\n\\n"
            f"Generate up to {max_journeys} grounded, high-value user journeys. Designate exactly "
            "ONE primary core feature workflow as recommended=True with high confidence. "
            "Do NOT recommend auth/signup unless explicitly requested. Focus on the core value "
            "proposition grounded in observed evidence.\\n"
        )

        try:
            return await asyncio.wait_for(
                self.provider.generate_structured(system, user_prompt, AIGeneratedJourneyList),
                timeout=time_budget_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("AI journey synthesis timed out after %.0fs", time_budget_seconds)
            return None
        except AIProviderError as e:
            logger.warning("AI journey synthesis failed: %s", e)
            return None

    # ── Semantic Form Field Identification Fallback ─────────────────

    async def identify_auth_elements(
        self,
        current_url: str,
        candidates: list[dict],
        is_signup: bool = False,
    ) -> AuthFormSemanticResult | None:
        """Semantically identify email, password, and submit inputs from non-standard candidate elements."""
        if not self.provider or not candidates:
            return None

        flow_type = "Sign up / Account Creation" if is_signup else "Sign in / Log in"
        system = (
            "You are an expert browser automation element identifier. "
            "Given candidate interactive elements from a web page where heuristic CSS selectors failed, "
            "identify the candidate element indices corresponding to the authentication form fields.\n\n"
            "Identify:\n"
            "1. email_or_user_index: Candidate index for the email, username, phone, or identifier input.\n"
            "2. password_index: Candidate index for the password input (or null if multi-step step 1).\n"
            "3. submit_index: Candidate index for the primary submit or continue button.\n"
            "4. name_index: Candidate index for the user's full name or display name input (if registration).\n"
            "5. is_multi_step: True if this page currently only requests the identifier/email before password is shown.\n\n"
            "Respond ONLY with valid JSON matching the AuthFormSemanticResult schema."
        )

        user_prompt = (
            f"Action: {flow_type}\n"
            f"Current URL: {current_url}\n"
            f"Candidate Elements:\n{json.dumps(candidates[:60], indent=1)}"
        )

        try:
            return await self.provider.generate_structured(
                system, user_prompt, AuthFormSemanticResult
            )
        except AIProviderError as e:
            logger.warning("AI provider failed to semantically identify auth inputs: %s", e)
            return None
        except Exception as e:
            logger.warning("Unexpected error during semantic auth identification: %s", e)
            return None

    async def identify_auth_entrance(
        self,
        current_url: str,
        candidates: list[dict],
        is_signup: bool = False,
    ) -> AuthEntranceSemanticResult | None:
        """Semantically identify the button or link that opens the login or signup page/modal."""
        if not self.provider or not candidates:
            return None

        flow_type = "Sign up / Register / Create Account" if is_signup else "Sign in / Log in"
        system = (
            "You are an expert browser automation element identifier. "
            f"Given candidate interactive elements on a web page, identify the element index that opens or navigates to the {flow_type} view or modal.\n"
            "Return JSON matching AuthEntranceSemanticResult: {entrance_index: integer or null, confidence: float, reasoning: string}."
        )

        user_prompt = (
            f"Target flow: {flow_type}\n"
            f"Current URL: {current_url}\n"
            f"Candidate Interactive Elements:\n{json.dumps(candidates[:60], indent=1)}"
        )

        try:
            return await self.provider.generate_structured(
                system, user_prompt, AuthEntranceSemanticResult
            )
        except AIProviderError as e:
            logger.warning("AI provider failed to semantically identify auth entrance: %s", e)
            return None
        except Exception as e:
            logger.warning("Unexpected error during semantic auth entrance identification: %s", e)
            return None

    # ── Phase 7/8: Next-action proposal (the agent loop's brain) ────

    async def propose_next_action(
        self,
        memory: AgentMemory,
        interpretation: GoalInterpretation,
        observation: dict,
        recent_failure: str | None = None,
    ) -> ActionProposal:
        semantic_view = build_semantic_observation(observation)
        if self.provider:
            system = (
                "You are the decision-making core of a browser automation agent. "
                "Choose ONE next action. Output ONLY JSON. Actions allowed: navigate, "
                "click, type, clear, select, check, uncheck, wait, press, scroll, "
                "create_email, read_email, extract_link, observe, request_human, abort. "
                "Targets are semantic descriptions resolved by deterministic tooling: "
                "give candidate_text[] and role hints. Never put secrets in value; use "
                "credential_intent (email|password|new_password) for credential fields. "
                "If the page shows a human-input requirement (OTP, CAPTCHA, payment, "
                "ambiguous destructive action), request_human. If the objective is "
                "impossible, abort."
                + build_system_prompt_clause()
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Intent: " + interpretation.intent + "\n"
                "Memory: " + json.dumps(memory.compact_view()) + "\n"
                "Observation:\n" + taint_page_content(json.dumps(semantic_view)) + "\n"
                + ("Recent failure: " + recent_failure + "\n" if recent_failure else "")
                + "\nReturn JSON: {action, target, value, credential_intent, reason, "
                "expected_effect, verification, confidence}."
            )
            last_error: AIProviderError | None = None
            for attempt in range(2):
                try:
                    return await self.provider.generate_structured(system, prompt, ActionProposal)
                except AIProviderError as e:
                    last_error = e
                    logger.warning("AI action proposal failed (attempt %d/2): %s", attempt + 1, e)
                    if attempt == 0:
                        await asyncio.sleep(0.5)
            # Failover across providers is handled inside FailoverAIProvider. When
            # every provider is exhausted we fall back to a generic, non-state-machine
            # heuristic instead of silently replaying a benchmark flow (forgot-password,
            # signup, etc.) on a real site.
            logger.warning(
                "AI action proposal failed after retries; using generic fallback: %s", last_error
            )
        return self._heuristic_next_action(memory, interpretation, semantic_view, recent_failure)

    def _heuristic_next_action(
        self,
        memory: AgentMemory,
        interpretation: GoalInterpretation,
        observation: dict,
        recent_failure: str | None = None,
    ) -> ActionProposal:
        """Generic deterministic fallback (no benchmark-specific state machine).

        When the AI provider is unavailable or fails, we never silently replay a
        hardcoded flow (forgot-password, signup, etc.) on a real site. We only
        take safe, generic steps: dismiss consent interstitials, or hand control
        back to the human so the model can decide once it is available again.
        """
        buttons = observation.get("buttons", []) or []
        links = observation.get("links", []) or []
        text = (observation.get("text_excerpt") or "").lower()

        # Consent / interstitial (generic, site-agnostic)
        consent_btn = _find_semantic(buttons, links, (
            "accept all", "accept cookies", "i accept", "agree", "i agree",
            "got it", "dismiss", "close modal", "continue to site", "close dialog",
        ))
        if consent_btn and (
            observation.get("dialogs")
            or any(kw in text for kw in ("cookie", "consent", "privacy choices", "notice"))
        ):
            name_lower = (consent_btn.get("name") or "").lower()
            if not any(kw in name_lower for kw in ("submit", "sign up", "sign in", "log in", "reset", "recover", "send")):
                return _click_proposal(consent_btn, "Dismiss interstitial modal or cookie consent notice")

        # No safe, generic next action is identifiable without the model. Hand
        # back to the human instead of guessing a benchmark-specific flow.
        return ActionProposal(
            action="request_human",
            reason="AI provider unavailable and no deterministic next action is identifiable",
            expected_effect="Human decides the next step",
            confidence=0.5,
        )


    async def propose_recovery(
        self,
        memory: AgentMemory,
        failure: str,
        failure_code: str,
        observation: dict,
    ) -> RecoveryProposal:
        if self.provider:
            system = (
                "A browser automation step or verification failed. Propose intelligent recovery. Output ONLY JSON. "
                "strategy ∈ retry_same|alternative_target|alternative_route|observe_more|request_human|abort. "
                "If the page was redirected to an authentication barrier (e.g. /signin, /login) because the target route "
                "is protected, recognize that authentication is required and propose alternative_route or retry_same with auth. "
                "Destructive actions must never be retried blindly. "
                "When human input is needed (OTP, CAPTCHA, expired link requiring new "
                "email is OK to retry, payment), request_human."
                + build_system_prompt_clause()
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Memory: " + json.dumps(memory.compact_view()) + "\n"
                "Failure: " + failure_code + " — " + failure + "\n"
                "Observation:\n" + taint_page_content(json.dumps(build_semantic_observation(observation))) + "\n"
                "Return JSON: {strategy, alternative_target, reason, action?}."
            )
            try:
                return await self.provider.generate_structured(system, prompt, RecoveryProposal)
            except AIProviderError as e:
                logger.warning("Recovery via AI failed, using fallback: %s", e)
        return self._heuristic_recovery(failure_code, failure)

    def _heuristic_recovery(self, failure_code: str, failure: str) -> RecoveryProposal:
        if failure_code in ("TARGET_NOT_FOUND", "ACTION_FAILED"):
            return RecoveryProposal(
                strategy="observe_more",
                reason="Target missing — re-observe the page before choosing another path",
            )
        if failure_code in ("EMAIL_NOT_RECEIVED",):
            return RecoveryProposal(
                strategy="retry_same",
                reason="Email may still arrive — one bounded re-check is safe",
            )
        if failure_code in ("AUTH_BLOCKED", "AUTH_REQUIRED"):
            return RecoveryProposal(
                strategy="alternative_route",
                reason="Target is protected by authentication barrier — sign in before accessing destination",
            )
        if failure_code in ("RESET_LINK_EXPIRED", "UNEXPECTED_DIALOG"):
            return RecoveryProposal(
                strategy="request_human",
                reason=f"{failure_code} requires human judgment",
            )
        return RecoveryProposal(
            strategy="observe_more",
            reason="Unknown failure class — gather more information",
        )

    # ── Phase 11: Semantic verification ─────────────────────────────

    async def propose_verification(
        self,
        memory: AgentMemory,
        interpretation: GoalInterpretation,
        observation: dict,
        deterministic_facts: list[str],
    ) -> VerificationProposal:
        if self.provider:
            system = (
                "Decide whether the observed outcome satisfies the user's objective. "
                "You are advisory: the deterministic verifier remains authoritative. "
                "If your view conflicts with deterministic facts, the runtime will "
                "report UNVERIFIED. Output ONLY JSON."
                + build_system_prompt_clause()
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Success requirements: " + json.dumps(interpretation.success_requirements) + "\n"
                "Deterministic facts: " + json.dumps(deterministic_facts) + "\n"
                "Memory: " + json.dumps(memory.compact_view()) + "\n"
                "Observation:\n" + taint_page_content(json.dumps(build_semantic_observation(observation))) + "\n"
                "Return JSON: {intent_satisfied, reason, required_facts[], "
                "suggested_condition}."
            )
            try:
                return await self.provider.generate_structured(system, prompt, VerificationProposal)
            except AIProviderError as e:
                logger.warning("Verification via AI failed, using deterministic: %s", e)
        # Deterministic fallback: satisfied only when every requirement has a
        # matching established fact — conservative and honest.
        facts_blob = " ".join(deterministic_facts).lower()
        satisfied = bool(deterministic_facts) and all(
            self._requirement_covered(req, facts_blob)
            for req in interpretation.success_requirements
        )
        return VerificationProposal(
            intent_satisfied=satisfied,
            reason="deterministic fact matching" if satisfied else "requirements lack established facts",
            required_facts=interpretation.success_requirements,
        )

    def _requirement_covered(self, requirement: str, facts_blob: str) -> bool:
        req_words = [w for w in requirement.lower().split() if len(w) > 3]
        return any(w in facts_blob for w in req_words)

    async def classify_auth_page(self, observation: dict[str, Any]) -> AuthPageClassification:
        """Classify an ambiguous page into an auth kind using LLM semantic reasoning."""
        if self._provider is None:
            return AuthPageClassification(
                kind="ambiguous",
                confidence=0.4,
                reasoning="No AI provider available; preserving ambiguous classification",
            )
        system_prompt = (
            "You are a web test agent analyzing an ambiguous page to determine if it is an authentication "
            "or gated access page. Return an AuthPageClassification with kind in "
            "['login', 'signup', 'magic_link', 'oauth_redirect', 'otp_verification', 'not_auth', 'ambiguous'] "
            "and a confidence score between 0.0 and 1.0."
            + build_system_prompt_clause()
        )
        user_prompt = f"Page observation:\n{taint_page_content(json.dumps(observation, default=str)[:4000])}"
        try:
            res = await self._provider.generate_structured(
                system=system_prompt,
                prompt=user_prompt,
                schema=AuthPageClassification,
            )
            if isinstance(res, AuthPageClassification):
                return res
            return AuthPageClassification.model_validate(res)
        except Exception as e:
            logger.warning("AI classify_auth_page failed: %s", e)
            return AuthPageClassification(
                kind="ambiguous",
                confidence=0.4,
                reasoning=f"AI classification failed: {e}",
            )

    async def propose_submit_button(self, observation: dict[str, Any]) -> str | None:
        """Propose a CSS selector or locator for a form submit button when deterministic search fails."""
        if self._provider is None:
            return None
        system_prompt = (
            "Analyze the page elements to identify the form submit button. "
            "Avoid OAuth/SSO buttons (Google, GitHub, etc.). "
            "Return a JSON object with 'selector' (CSS selector) and 'confidence'."
            + build_system_prompt_clause()
        )
        user_prompt = f"Page elements:\n{taint_page_content(json.dumps(observation.get('elements', []), default=str)[:3000])}"
        try:
            res = await self._provider.generate_structured(
                system=system_prompt,
                prompt=user_prompt,
                schema=SubmitButtonProposal,
            )
            if res and res.selector:
                return res.selector
        except Exception as e:
            logger.warning("AI propose_submit_button failed: %s", e)
        return None

    async def propose_flows(
        self,
        goal_name: str,
        product_graph_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Propose executable flow candidates for an unresolved goal.

        Returns a list of dicts with flow proposals: {name, steps, confidence, reasoning}.
        Confidence is strictly capped at <= 0.9.
        """
        provider = self.provider or getattr(self, "_provider", None)
        if provider:
            system_prompt = (
                "You are an expert software test automation planner. Given a high-level goal and "
                "a summary of discovered application pages and interactive elements from the Product Graph, "
                "propose an executable flow to achieve the goal.\n"
                "Respond ONLY with a JSON list of flow objects, each containing: "
                "'name' (string), 'steps' (list of {action, target, value, description}), "
                "'confidence' (float <= 0.9), and 'reasoning' (string)."
            )
            user_prompt = (
                f"Goal: {goal_name}\n"
                f"Product Graph context: {json.dumps(product_graph_summary, default=str)[:3000]}\n"
            )
            try:
                res = await provider.generate_structured(
                    system=system_prompt,
                    prompt=user_prompt,
                    schema=ProposedFlowList,
                )
                if res and res.flows:
                    flow_dicts: list[dict[str, Any]] = []
                    for f in res.flows:
                        fd = f.model_dump()
                        fd["confidence"] = min(float(fd.get("confidence", 0.8)), 0.9)
                        flow_dicts.append(fd)
                    return flow_dicts
            except Exception as e:
                logger.warning("AI propose_flows failed: %s", e)

        # Conservative heuristic fallback
        return [
            {
                "name": f"AI Proposed Flow for {goal_name}",
                "steps": [
                    {"action": "navigate", "target": "/", "value": "/", "description": "Navigate to home"},
                    {"action": "wait", "target": "", "value": "1000", "description": f"Wait for page load for {goal_name}"},
                ],
                "confidence": 0.75,
                "reasoning": f"Heuristic flow proposal for unresolved goal '{goal_name}'",
            }
        ]

    async def propose_failure_hypothesis(
        self,
        execution_id: str,
        events: list[dict],
        verification_checks: list[dict],
        evidence_summary: dict,
    ) -> FailureHypothesis | None:
        """AI-driven failure diagnosis.

        Correlates failed assertions, browser observations, screenshots, and network
        evidence to propose a plausible root cause.
        """
        if not self.provider:
            return self._heuristic_failure_hypothesis(events, verification_checks)

        failure_events = [e for e in events if "fail" in e.get("type", "").lower() or "error" in e.get("type", "").lower()]
        failed_checks = [c for c in verification_checks if c.get("verdict") == "failed"]

        # Collect all valid evidence IDs present in events or checks
        valid_evidence_ids = set()
        for e in events:
            if "evidence_id" in e:
                valid_evidence_ids.add(str(e["evidence_id"]))
            if "id" in e and "evidence" in e.get("type", "").lower():
                valid_evidence_ids.add(str(e["id"]))
        for c in verification_checks:
            for eid in c.get("evidence_ids", []):
                valid_evidence_ids.add(str(eid))

        system_prompt = (
            "You are diagnosing the root cause of a failed software validation run. "
            "Correlate the failed assertions, browser observations, and network evidence "
            "to propose the most plausible root cause. "
            "Cite specific evidence IDs in your hypothesis. "
            "If the evidence is insufficient to determine a root cause, say so explicitly — "
            "do not invent an explanation. "
            "Provide 1-2 alternative explanations ranked by likelihood. "
            "Recommend a concrete next investigation step."
            + build_system_prompt_clause()
        )
        user_prompt = json.dumps({
            "execution_id": execution_id,
            "failure_events": failure_events[:20],
            "failed_verification_checks": failed_checks,
            "evidence_summary": {
                "screenshot_count": evidence_summary.get("screenshot_count", 0),
                "network_log_entries": evidence_summary.get("network_log_entries", [])[:10],
                "dom_snapshots": evidence_summary.get("dom_snapshot_count", 0),
                "console_errors": evidence_summary.get("console_errors", [])[:10],
            },
        }, default=str)[:6000]

        try:
            res: FailureHypothesis = await self.provider.generate_structured(
                system=system_prompt,
                prompt=user_prompt,
                schema=FailureHypothesis,
            )
            # Anti-hallucination guard: filter cited evidence IDs to known valid IDs if known IDs exist
            if valid_evidence_ids:
                res.evidence_cited = [eid for eid in res.evidence_cited if eid in valid_evidence_ids]
            return res
        except (AIProviderError, Exception) as e:
            logger.warning("propose_failure_hypothesis AI call failed: %s", e)
            return self._heuristic_failure_hypothesis(events, verification_checks)

    def _heuristic_failure_hypothesis(self, events: list[dict], verification_checks: list[dict]) -> FailureHypothesis:
        """Conservative heuristic: cite the first failed check as the root cause."""
        failed = [c for c in verification_checks if c.get("verdict") == "failed"]
        if not failed:
            return FailureHypothesis(
                root_cause="No failed verification checks found; the failure may be environmental.",
                confidence=0.3,
                evidence_cited=[],
                alternative_explanations=[],
                recommended_investigation="Check the execution logs for unexpected errors.",
                reproduction_steps=[],
            )
        first_failure = failed[0]
        check_name = first_failure.get("name", "unknown")
        check_reason = first_failure.get("reason", "no reason provided")
        evidence_ids = [str(eid) for eid in first_failure.get("evidence_ids", [])]

        return FailureHypothesis(
            root_cause=f"Verification check '{check_name}' failed: {check_reason}",
            confidence=0.5,
            evidence_cited=evidence_ids,
            alternative_explanations=["The check itself may be incorrectly specified"],
            recommended_investigation=f"Inspect the evidence linked to check '{check_name}' and verify the assertion is correct.",
            reproduction_steps=[],
        )

    async def synthesize_report_summary(
        self,
        validation_report: dict,
    ) -> ReportSummary | None:
        """AI-driven report synthesis for the human-readable summary section."""
        if not self.provider:
            return self._heuristic_report_summary(validation_report)

        system_prompt = (
            "You are writing a concise summary of a software validation report for an engineer. "
            "The summary should help the engineer quickly understand: "
            "(1) what was validated, (2) what passed, (3) what failed, (4) what to do next. "
            "Be specific and actionable. Avoid generic statements like 'investigate the issue'. "
            "Cite specific flows, evidence, or failure categories. "
            "If the validation passed cleanly, say so concisely."
            + build_system_prompt_clause()
        )
        user_prompt = json.dumps({
            "overall_status": validation_report.get("overall_status"),
            "flows_count": len(validation_report.get("results", [])),
            "passed_count": sum(1 for r in validation_report.get("results", []) if r.get("status") == "passed"),
            "failed_count": sum(1 for r in validation_report.get("results", []) if r.get("status") == "failed"),
            "unverified_count": sum(1 for r in validation_report.get("results", []) if r.get("status") == "unverified"),
            "failed_flows": [
                {"name": r.get("flow_name"), "failure_reason": r.get("failure_reason")}
                for r in validation_report.get("results", [])
                if r.get("status") == "failed"
            ][:5],
            "duration_seconds": validation_report.get("duration_ms", 0) / 1000,
        }, default=str)[:4000]

        try:
            res: ReportSummary = await self.provider.generate_structured(
                system=system_prompt,
                prompt=user_prompt,
                schema=ReportSummary,
            )
            return res
        except (AIProviderError, Exception) as e:
            logger.warning("synthesize_report_summary AI call failed: %s", e)
            return self._heuristic_report_summary(validation_report)

    def _heuristic_report_summary(self, validation_report: dict) -> ReportSummary:
        """Deterministic summary when AI is unavailable."""
        results = validation_report.get("results", [])
        passed = sum(1 for r in results if r.get("status") == "passed")
        failed = sum(1 for r in results if r.get("status") == "failed")
        overall = validation_report.get("overall_status", "unknown")

        failed_names = [r.get("flow_name", "unnamed") for r in results if r.get("status") == "failed"]
        next_steps = (
            [f"Review failures in: {', '.join(failed_names)}"]
            if failed_names
            else ["Proceed with build and deployment."]
        )

        return ReportSummary(
            headline=f"Validation {overall}: {passed} passed, {failed} failed, {len(results)} total flows",
            key_findings=[
                f"Overall status: {overall}",
                f"Passed: {passed}/{len(results)}",
                f"Failed: {failed}/{len(results)}",
            ],
            overall_assessment=f"The validation run completed with overall status '{overall}'. See per-flow results for details.",
            confidence=0.7,
            recommended_next_steps=next_steps,
        )

    async def evaluate_scenario_validity(
        self,
        flow: dict,
        new_page_state: dict,
        original_graph_version: int,
    ) -> ScenarioValidityAssessment:
        """AI-driven assessment of whether a test scenario remains valid after UI drift.

        Preserves original acceptance criteria and proposes locator updates for review.
        """
        if not self.provider:
            return self._heuristic_validity_assessment(flow, new_page_state)

        system_prompt = (
            "You are evaluating whether an existing test scenario is still valid "
            "after the application's interface has changed. "
            "Your job: determine whether the original acceptance criteria can still be "
            "checked against the new page state. "
            "DO NOT propose changes to the acceptance criteria themselves — only to "
            "the locators/selectors used to check them. "
            "If the criteria can no longer be checked (e.g. the feature was removed), "
            "mark is_still_valid=false and requires_review=true. "
            "If the locators moved but the feature is intact, propose updated locators "
            "with high confidence. "
            "Never propose weakening the criteria to make the test pass."
            + build_system_prompt_clause()
        )
        user_prompt = json.dumps({
            "flow_objective": flow.get("objective"),
            "flow_success_condition": flow.get("success_condition"),
            "flow_steps_summary": [
                {"type": s.get("type", s.get("action")), "target": s.get("target") or s.get("selector")}
                for s in flow.get("steps", [])
            ],
            "new_page_state": {
                "url": new_page_state.get("url"),
                "available_buttons": new_page_state.get("buttons", []),
                "available_forms": new_page_state.get("forms", []),
                "current_locators_for_original_steps": new_page_state.get("locator_matches", []),
            },
            "original_graph_version": original_graph_version,
        }, default=str)[:6000]

        try:
            res: ScenarioValidityAssessment = await self.provider.generate_structured(
                system=system_prompt,
                prompt=user_prompt,
                schema=ScenarioValidityAssessment,
            )
            if not res.flow_id:
                res.flow_id = str(flow.get("id", ""))
            return res
        except (AIProviderError, Exception) as e:
            logger.warning("evaluate_scenario_validity AI call failed: %s", e)
            return self._heuristic_validity_assessment(flow, new_page_state)

    def _heuristic_validity_assessment(self, flow: dict, new_page_state: dict) -> ScenarioValidityAssessment:
        """Conservative heuristic: if any locator from the original flow is missing
        in the new page state, mark as requires_review."""
        original_steps = flow.get("steps", [])
        new_locator_matches = new_page_state.get("locator_matches", [])
        matched_targets = {
            m.get("original_target")
            for m in new_locator_matches
            if isinstance(m, dict) and m.get("original_target")
        }
        missing_locators = []
        for s in original_steps:
            stype = (s.get("type") or s.get("action") or "").lower()
            target = s.get("target") or s.get("selector")
            if stype in ("click", "input", "type", "fill", "select") and target:
                target_str = str(target)
                if new_locator_matches and target_str not in matched_targets:
                    missing_locators.append(s)

        requires_rev = len(missing_locators) > 0
        return ScenarioValidityAssessment(
            flow_id=str(flow.get("id", "")),
            is_still_valid=len(missing_locators) == 0,
            confidence=0.5 if requires_rev else 0.8,
            changes_detected=[
                f"Locator '{s.get('target') or s.get('selector')}' for step '{s.get('description', s.get('type', s.get('action')))}' not found in new page"
                for s in missing_locators
            ],
            acceptance_criteria_impacted=[] if not missing_locators else ["Locators required to check criteria are missing"],

            requires_review=requires_rev,
            proposed_locator_updates=[],
            reasoning=(
                "Heuristic assessment: missing locators detected; cannot verify criteria without human review."
                if requires_rev
                else "Heuristic assessment: step locators verified in new page state."
            ),
        )




# ── Semantic helpers (§7: no exact-string matching) ─────────────────


def _find_semantic(
    buttons: dict[str, dict] | list[dict],
    links: dict[str, dict] | list[dict],
    candidates: tuple[str, ...],
) -> dict | None:
    """Find a button/link whose accessible name contains any candidate phrase."""
    elements: list[dict] = []
    if isinstance(buttons, dict):
        elements.extend(buttons.values())
    elif isinstance(buttons, (list, tuple)):
        elements.extend(buttons)

    if isinstance(links, dict):
        elements.extend(links.values())
    elif isinstance(links, (list, tuple)):
        elements.extend(links)

    for el in elements:
        name = (el.get("name") or "").lower()
        for cand in candidates:
            if cand in name:
                return el
    return None


def _click_proposal(element: dict, reason: str) -> ActionProposal:
    selector = element.get("selector") or ""
    target: dict = {"candidate_text": [element.get("name", "")]}
    if element.get("role"):
        target["role"] = element["role"]
    if selector:
        target["css"] = selector
    return ActionProposal(
        action="click",
        target=target,
        reason=reason,
        expected_effect="Navigation or state change toward the objective",
        confidence=0.7,
    )
