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
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.engine.ai.memory import AgentMemory
from app.engine.ai.observation import build_semantic_observation
from app.engine.ai.provider import AIProvider, AIProviderError
from app.engine.ai.schemas import (
    ActionProposal,
    AIGeneratedJourney,
    AIGeneratedJourneyList,
    AuthEntranceSemanticResult,
    AuthFormSemanticResult,
    AuthPageClassification,
    GoalInterpretation,
    JourneyPlan,
    ProposedStep,
    RecoveryProposal,
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
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Structured intent: " + json.dumps(interpretation.model_dump()) + "\n"
                "Current observation: " + json.dumps(semantic_view) + "\n"
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
        routes: list[dict],
        interactive_elements: list[dict],
        page_summary: str = "",
        max_journeys: int = 5,
    ) -> AIGeneratedJourneyList | None:
        """Synthesize intelligent, purposeful user journeys that test real features of the app."""
        if not self.provider:
            return None

        # Compact representation of available routes (prioritizing feature, dashboard, and content)
        compact_routes = [
            {
                "path": r.get("path"),
                "title": r.get("title") or r.get("text"),
                "category": r.get("category"),
                "requires_auth": r.get("requires_auth", False),
                "elements_count": r.get("elements_count", 0),
            }
            for r in routes[:20]
            if r.get("path")
        ]

        # Compact representation of interactive elements (buttons, links, inputs)
        compact_elements = [
            {
                "name": el.get("name"),
                "type": el.get("type"),
                "role": el.get("role"),
            }
            for el in interactive_elements[:30]
            if el.get("name")
        ]

        system = (
            "You are an expert QA and product automation architect. Your mission is to discover "
            "and synthesize HIGH-VALUE, PURPOSEFUL user journeys that thoroughly test the core features, "
            "dashboards, workflows, and interactive capabilities of the web application.\n\n"
            "CRITICAL RULES:\n"
            "1. AUTH IS NOT THE PRODUCT: Authentication/Signup is NEVER a recommended user journey. Do NOT generate 'Sign up and log in' "
            "or 'Sign up, log in, and verify account' as primary journeys. In modern web testing, auth is a given infrastructure prerequisite "
            "that Kova handles automatically when hitting an auth wall. The journeys must focus on what the user actually DOES in the app: "
            "dashboards, features, document management, quizzes, study sets, workflows, data creation, search, analytics, etc.\n"
            "2. UTILITY IS NOT CORE: Settings, user profile, account details, or terms are utility areas and must NEVER be the recommended journey "
            "unless the user explicitly requested it in their goal.\n"
            "3. PURPOSEFUL FEATURE WORKFLOWS: The RECOMMENDED journey MUST test the application's core value proposition (e.g., generating or taking quizzes "
            "for a study platform; creating a study set or flashcards; uploading and summarizing documents; exploring resource libraries; "
            "inspecting analytics and activity metrics for a dashboard). Infer features from landing page headlines and text even if behind an auth gate.\n"
            "4. ACTION-ORIENTED TITLES: Use meaningful titles reflecting real user intent (e.g. 'Generate and Practice Interactive Quiz', "
            "'Upload Study Material and Review Summaries', 'Create and Practice Flashcards', 'Search and Explore Resource Library') rather than generic 'Open X'.\n"
            "5. INTERACTIVE BUTTONS & MODALS: Features in modern SPAs are often activated by clicking buttons (e.g. 'Create Quiz', 'New Study Set', 'Upload Material', "
            "'Start Practice', tabs, modals, drawers) rather than navigating to a separate URL route. When a feature has an action button or control, synthesize steps "
            "that click the button (`click` action targeting e.g. `button:has-text('Upload')` or `button:has-text('Create')`) and verify the resulting view, dialog, or content opens. "
            "Do not restrict yourself to URL navigation only; test buttons and interactive UI actions directly.\n"
            "6. STEPS: Steps must use valid browser actions: navigate, click, fill, select, wait.\n"
            "7. VERIFIABILITY: The success condition must specify verifiable criteria grounded in observed UI (text_visible, element_visible, url_changed_to, etc.).\n"
            "8. Output ONLY JSON matching the AIGeneratedJourneyList schema."
        )

        user_prompt = (
            f"Application URL: {base_url}\n"
            f"Page Title: {title}\n"
            f"Primary Persona: {persona}\n"
            f"User Goal: {goal or 'Thoroughly test core application features'}\n"
            f"Page Content & Summary: {page_summary[:1500]}\n\n"
            f"Discovered Routes:\n{json.dumps(compact_routes, indent=1)}\n\n"
            f"Observed Controls/Elements:\n{json.dumps(compact_elements, indent=1)}\n\n"
            f"Generate up to {max_journeys} intelligent, high-value user journeys that test real features. "
            "Designate exactly ONE primary core feature workflow as recommended=True with high confidence. "
            "Do NOT recommend auth/signup. Focus on the core value proposition of the product."
        )

        try:
            return await self.provider.generate_structured(
                system, user_prompt, AIGeneratedJourneyList
            )
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
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Intent: " + interpretation.intent + "\n"
                "Memory: " + json.dumps(memory.compact_view()) + "\n"
                "Observation: " + json.dumps(semantic_view) + "\n"
                + ("Recent failure: " + recent_failure + "\n" if recent_failure else "")
                + "\nReturn JSON: {action, target, value, credential_intent, reason, "
                "expected_effect, verification, confidence}."
            )
            try:
                return await self.provider.generate_structured(system, prompt, ActionProposal)
            except AIProviderError as e:
                logger.warning("Action proposal via AI failed, using heuristics: %s", e)
        return self._heuristic_next_action(memory, interpretation, semantic_view, recent_failure)

    def _heuristic_next_action(
        self,
        memory: AgentMemory,
        interpretation: GoalInterpretation,
        observation: dict,
        recent_failure: str | None = None,
    ) -> ActionProposal:
        """Deterministic state-machine proposal for the forgot-password class.

        Implements the benchmark flow semantically WITHOUT a hardcoded DOM.
        Phase order advances only on real executor-reported state:
          email → signup → verify → login → logout → forgot → mailbox → reset
        Reacts to what the observation actually contains, using semantic
        equivalence classes instead of exact strings (spec §7).
        """
        identity = memory.identity
        buttons = {(b.get("name") or "").lower(): b for b in observation.get("buttons", [])}
        links = {(l.get("name") or "").lower(): l for l in observation.get("links", [])}
        inputs = observation.get("inputs", [])
        text = (observation.get("text_excerpt") or "").lower()
        signals = observation.get("auth_signals", [])

        def _has_email(i: dict) -> bool:
            return "email" in (
                i.get("input_type", "") + " " + i.get("name", "") + " "
                + i.get("label", "") + " " + i.get("placeholder", "")
            ).lower()

        def _empty(of_type: tuple[str, ...] = ()) -> list[dict]:
            """Empty (unfilled) inputs, optionally filtered by input_type."""
            return [
                i for i in inputs
                if not i.get("filled") and (not of_type or i.get("input_type") in of_type)
            ]

        def _input_target(inp: dict) -> dict:
            """Deterministic input target: specific selector or name attribute."""
            sel = inp.get("selector") or ""
            if sel and not sel.startswith(("input[", "textarea[")):
                return {"css": sel}
            name = (inp.get("name") or "").strip()
            if name and not name.startswith(("#", ".", "input", "textarea")):
                return {"css": f"input[name='{name}']"}
            return {"css": sel or "input"}

        # Real-page evidence updates authenticated state (never guessed)
        if "authenticated_indicators" in signals and "password_field_present" not in signals:
            identity.authenticated = True
        elif "password_field_present" in signals and identity.authenticated:
            if "login_page_url" in signals or any("log in" in b or "log in" in l for b, l in
                                                   [(b, b) for b in buttons] + [(l, l) for l in links]):
                identity.authenticated = False

        # ── Interstitial / Consent Modal Handling (Variant M) ──
        consent_btn = _find_semantic(buttons, links, (
            "accept all", "accept cookies", "i accept", "agree", "i agree",
            "got it", "dismiss", "close modal", "continue to site", "close dialog",
        ))
        if consent_btn and (observation.get("dialogs") or any(kw in text for kw in ("cookie", "consent", "privacy choices", "notice"))):
            name_lower = (consent_btn.get("name") or "").lower()
            if not any(kw in name_lower for kw in ("submit", "sign up", "sign in", "log in", "reset", "recover", "send")):
                return _click_proposal(consent_btn, "Dismiss interstitial modal or cookie consent notice")

        # ── Phase R3: reset form open (after reset link) → set new password ──
        if identity.reset_link_opened and not identity.password_reset:
            pw_empty = _empty(("password",))
            if pw_empty:
                target = _input_target(pw_empty[0])
                if len(pw_empty) >= 2:
                    target["confirm_css"] = _input_target(pw_empty[1])["css"]
                return ActionProposal(
                    action="type",
                    target=target,
                    credential_intent="new_password",
                    reason="Reset form open — setting the new password",
                    expected_effect="New password entered",
                    confidence=0.8,
                )
            if inputs:  # fields filled → submit
                sub_btn = _find_semantic(buttons, [], ("reset", "update password", "set password", "save", "change password", "submit"))
                if sub_btn:
                    return _click_proposal(sub_btn, "Submitting the reset form via button")
                return ActionProposal(
                    action="press",
                    value="Enter",
                    reason="Submitting the reset form",
                    expected_effect="Password changed",
                    confidence=0.7,
                )

        # ── Phase R2: recovery requested → read mailbox for reset mail ──
        if identity.recovery_requested and not identity.reset_link_opened:
            return ActionProposal(
                action="read_email",
                target={"subject_keywords": ["reset", "recover", "password", "instructions"]},
                reason="Recovery email expected — checking the mailbox",
                expected_effect="Reset link retrieved",
                confidence=0.8,
            )

        # ── Phase E: no identity → create the mailbox first ──
        if interpretation.needs_email_capability and not identity.email:
            return ActionProposal(
                action="create_email",
                reason="Establish a temporary email identity for the whole execution",
                expected_effect="A persistent mailbox address is available",
                confidence=0.9,
            )

        # ── Phase R1: unauthenticated state → forgot-password flow with SAME email ──
        ready_for_recovery = (
            (not interpretation.needs_account or identity.account_created)
            and (identity.logged_out or not interpretation.needs_account)
            and not identity.authenticated
            and not identity.recovery_requested
        )
        if ready_for_recovery:
            # Check for dedicated recovery inputs (e.g. In modal dialogs)
            rec_inputs = [i for i in _empty() if "recovery" in (i.get("selector", "") + " " + i.get("name", "") + " " + i.get("label", "")).lower()]
            if rec_inputs:
                return ActionProposal(
                    action="type",
                    target=_input_target(rec_inputs[0]),
                    credential_intent="email",
                    reason="Modal recovery form detected — submitting the SAME identity email",
                    expected_effect="Recovery request submitted for the persistent identity",
                    confidence=0.7,
                )
            rec_filled = [i for i in inputs if i.get("filled") and "recovery" in (i.get("selector", "") + " " + i.get("name", "") + " " + i.get("label", "")).lower()]
            if rec_filled:
                sub_btn = _find_semantic(buttons, [], ("send", "submit", "continue", "reset", "recover", "email"))
                if sub_btn:
                    return _click_proposal(sub_btn, "Submitting the recovery form via button")

            email_empty = [i for i in _empty(("email",)) if _has_email(i)]
            if email_empty and "password_field_present" not in signals:
                return ActionProposal(
                    action="type",
                    target=_input_target(email_empty[0]),
                    credential_intent="email",
                    reason="Recovery form detected — submitting the SAME identity email",
                    expected_effect="Recovery request submitted for the persistent identity",
                    confidence=0.7,
                )
            if any(i.get("filled") and _has_email(i) for i in inputs) \
                    and "password_field_present" not in signals:
                sub_btn = _find_semantic(buttons, [], ("send", "submit", "continue", "reset", "recover", "email"))
                if sub_btn:
                    return _click_proposal(sub_btn, "Submitting the recovery form via button")
                return ActionProposal(
                    action="press",
                    value="Enter",
                    reason="Submitting the recovery form",
                    expected_effect="Recovery email sent",
                    confidence=0.7,
                )
            recovery = _find_semantic(buttons, links, RECOVERY_TEXTS)
            if recovery:
                return _click_proposal(recovery, "Open the password recovery flow")

        # ── Phase V: verification prompt → read mailbox for verification mail ──
        if "email_verification_prompt" in signals and not identity.account_verified:
            return ActionProposal(
                action="read_email",
                target={"subject_keywords": ["verify", "confirm", "activate"]},
                reason="Application requests email verification — checking the mailbox",
                expected_effect="A verification message with a link is found",
                confidence=0.7,
            )

        # ── Phase A: authenticated → log out before recovery flows ──
        if identity.authenticated and not identity.logged_out:
            logout = _find_semantic(buttons, links, LOGOUT_TEXTS)
            if logout:
                return _click_proposal(logout, "Log out to start the recovery flow from a clean state")

        # ── Phase S: no account yet → signup flow (BEFORE recovery) ──
        if identity.email and not identity.account_created and interpretation.needs_account:
            # Prefer the explicit signup entry point: on a login page the
            # email+password form is the LOGIN form, not signup — filling it
            # would submit credentials for an account that doesn't exist.
            signup = _find_semantic(buttons, links, SIGNUP_TEXTS)
            if signup:
                return _click_proposal(signup, "No account yet — open signup")
            # No signup link visible → we're on the signup form → fill it
            email_empty = [i for i in _empty() if _has_email(i)]
            pw_empty = _empty(("password",))
            email_filled = any(_has_email(i) for i in inputs if i.get("filled"))
            pw_filled = any(i.get("filled") for i in inputs if i.get("input_type") == "password")
            if email_empty and pw_empty:
                return ActionProposal(
                    action="type",
                    target=_input_target(email_empty[0]),
                    credential_intent="email",
                    reason="Signup form detected — creating the account with the identity email",
                    expected_effect="Signup form filled",
                    confidence=0.7,
                )
            if email_filled and pw_empty:
                return ActionProposal(
                    action="type",
                    target=_input_target(pw_empty[0]),
                    credential_intent="password",
                    reason="Signup form — entering the account password",
                    expected_effect="Signup form filled",
                    confidence=0.7,
                )
            if email_filled and pw_filled:
                sub_btn = _find_semantic(buttons, [], ("create", "sign up", "register", "create account", "submit", "continue", "join"))
                if sub_btn:
                    return _click_proposal(sub_btn, "Submitting the signup form via button")
                return ActionProposal(
                    action="press",
                    value="Enter",
                    reason="Submitting the signup form",
                    expected_effect="Account created / verification required",
                    confidence=0.7,
                )

        # ── Phase L: verified account → login ──
        if identity.email and identity.account_verified and not identity.authenticated:
            login_link = _find_semantic(buttons, links, LOGIN_TEXTS)
            if login_link:
                return _click_proposal(login_link, "Open the login form")
            email_empty = [i for i in _empty() if _has_email(i)]
            pw_empty = _empty(("password",))
            email_filled = any(_has_email(i) for i in inputs if i.get("filled"))
            pw_filled = any(i.get("filled") for i in inputs if i.get("input_type") == "password")
            if email_empty:
                return ActionProposal(
                    action="type",
                    target=_input_target(email_empty[0]),
                    credential_intent="email",
                    reason="Login form detected — entering the identity email",
                    expected_effect="Login form filled",
                    confidence=0.7,
                )
            if pw_empty:
                return ActionProposal(
                    action="type",
                    target=_input_target(pw_empty[0]),
                    credential_intent="password",
                    reason="Login form detected — entering the password",
                    expected_effect="Login form filled",
                    confidence=0.7,
                )
            if email_filled and pw_filled:
                sub_btn = _find_semantic(buttons, [], ("log in", "sign in", "submit", "continue", "enter", "access"))
                if sub_btn:
                    return _click_proposal(sub_btn, "Submitting the login form via button")
                return ActionProposal(
                    action="press",
                    value="Enter",
                    reason="Submitting the login form",
                    expected_effect="Authenticated state",
                    confidence=0.7,
                )


        # ── Default: observe more (never guess blindly) ──
        return ActionProposal(
            action="observe",
            reason="No confident next action from current observation — gathering more detail",
            expected_effect="Richer observation for the next decision",
            confidence=0.2,
        )

    # ── Phase 8: Recovery ───────────────────────────────────────────

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
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Memory: " + json.dumps(memory.compact_view()) + "\n"
                "Failure: " + failure_code + " — " + failure + "\n"
                "Observation: " + json.dumps(build_semantic_observation(observation)) + "\n"
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
            )
            prompt = (
                "Objective: " + memory.objective + "\n"
                "Success requirements: " + json.dumps(interpretation.success_requirements) + "\n"
                "Deterministic facts: " + json.dumps(deterministic_facts) + "\n"
                "Memory: " + json.dumps(memory.compact_view()) + "\n"
                "Observation: " + json.dumps(build_semantic_observation(observation)) + "\n"
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
        )
        user_prompt = f"Page observation:\n{json.dumps(observation, default=str)[:4000]}"
        try:
            res = await self._provider.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
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
        )
        user_prompt = f"Page elements:\n{json.dumps(observation.get('elements', []), default=str)[:3000]}"
        try:
            res = await self._provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            match = re.search(r'"selector":\s*"([^"]+)"', res)
            if match:
                return match.group(1)
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
                res = await provider.generate(system_prompt=system_prompt, user_prompt=user_prompt)
                match = re.search(r"\[.*\]", res, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list):
                        for p in parsed:
                            p["confidence"] = min(float(p.get("confidence", 0.8)), 0.9)
                        return parsed
            except Exception as e:
                logger.warning("AI propose_flows failed: %s", e)

        # Conservative heuristic fallback
        return [
            {
                "name": f"AI Proposed Flow for {goal_name}",
                "steps": [
                    {"action": "navigate", "target": "/", "value": "/", "description": "Navigate to home"},
                    {"action": "assert", "target": "page_loaded", "value": "/", "description": f"Verify entry for {goal_name}"},
                ],
                "confidence": 0.75,
                "reasoning": f"Heuristic flow proposal for unresolved goal '{goal_name}'",
            }
        ]


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
