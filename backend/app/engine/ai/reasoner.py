"""Agent reasoning capabilities over the AI provider abstraction.

Each capability degrades gracefully: when AI is unavailable, deterministic
heuristics return conservative structured results so the agent loop can still
run (with reduced semantic adaptivity). AI output is ALWAYS a proposal — the
agent executor validates and executes it through the deterministic runtime.

Cost discipline (spec §27): AI is called only at semantic decision points —
goal interpretation, journey planning, next-action selection, recovery, and
final verification — never per DOM node.
"""

import json
import logging
import re
from urllib.parse import urlparse

from app.engine.ai.memory import AgentMemory
from app.engine.ai.observation import build_semantic_observation
from app.engine.ai.provider import AIProvider, AIProviderError
from app.engine.ai.schemas import (
    ActionProposal,
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
                "A browser automation step failed. Propose recovery. Output ONLY JSON. "
                "strategy ∈ retry_same|alternative_target|alternative_route|observe_more|"
                "request_human|abort. Destructive actions must never be retried blindly. "
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
        if failure_code in ("RESET_LINK_EXPIRED", "AUTH_REQUIRED", "UNEXPECTED_DIALOG"):
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
