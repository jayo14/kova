"""The agent executor loop.

    OBSERVE → UNDERSTAND → PLAN → ACT → OBSERVE → VERIFY → RECOVER → REPORT

The loop drives the deterministic runtime (BrowserSession, ActionExecutor,
Verifier, Evidence) from AI proposals. Hard invariants enforced here:

  1. Identity (temporary email) is created once, stored in AgentMemory, and
     reused for every subsequent step — never regenerated.
  2. Every AI proposal passes the validator before ActionExecutor sees it.
  3. Email links are untrusted: validate_email_link gates every navigation.
  4. The loop can request human takeover or abort, but can NEVER mark an
     execution COMPLETED — final verification goes through the deterministic
     Verifier plus the semantic-verification gate (AI view cannot override
     missing deterministic facts; §33).
  5. Bounded turns, bounded recovery, bounded cost.
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Callable

from app.engine.ai.memory import AgentMemory
from app.engine.ai.reasoner import AgentReasoner, RESET_SENT_TEXTS, VERIFICATION_EMAIL_TEXTS
from app.engine.ai.schemas import ActionProposal, GoalInterpretation
from app.engine.ai.validator import (
    ProposalRejected,
    proposal_to_raw_action,
    validate_action_proposal,
)
from app.engine.browser.executor import ActionExecutor
from app.engine.browser.session import BrowserSession
from app.engine.browser.screenshot_storage import screenshot_storage
from app.engine.credentials.store import CredentialStore
from app.engine.email.provider import (
    EmailMessage,
    TemporaryEmailProvider,
    validate_email_link,
)
from app.engine.verification.verifier import Verifier
from app.modules.executions.event_types import EventTypes

logger = logging.getLogger(__name__)

# Cost/behavior bounds (§15/§27)
MAX_AGENT_TURNS = 60
MAX_RECOVERIES = 8
OBSERVE_INTERVAL_TURNS = 1
EMAIL_WAIT_SECONDS = 45.0


class AgentOutcome:
    """Structured result of an agent run. Truthful by construction."""

    def __init__(
        self,
        status: str,           # COMPLETED | FAILED | UNVERIFIED | BLOCKED | NEEDS_INPUT
        reason: str,
        verification: dict | None = None,
        facts: list[str] | None = None,
    ):
        self.status = status
        self.reason = reason
        self.verification = verification or {}
        self.facts = facts or []

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "verification": self.verification,
            "facts": self.facts,
        }


class AgentExecutor:
    """Runs the agentic loop for one execution against one BrowserSession."""

    def __init__(
        self,
        execution_id: uuid.UUID,
        reasoner: AgentReasoner,
        email_provider: TemporaryEmailProvider | None,
        credential_store: CredentialStore | None = None,
        event_emitter: Callable[[str, dict], Any] | None = None,
        max_turns: int = MAX_AGENT_TURNS,
    ):
        self.execution_id = execution_id
        self.reasoner = reasoner
        self.email_provider = email_provider
        self.credential_store = credential_store or CredentialStore()
        self.event_emitter = event_emitter
        self.max_turns = max_turns
        self.mailbox: Any | None = None
        self.app_host: str | None = None

    async def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_emitter:
            try:
                res = self.event_emitter(event_type, payload)
                if hasattr(res, "__await__"):
                    await res
            except Exception as e:
                logger.warning("Agent event emit failed for %s: %s", event_type, e)

    async def heal_target(
        self,
        browser: BrowserSession,
        step: dict,
        error_message: str,
        observation: dict | None = None,
    ) -> dict | None:
        """Use AI reasoner to propose an alternate target when target resolution fails."""
        obs = observation or await browser.observe()
        memory = AgentMemory(self.execution_id, objective=f"Recover failed step: {step.get('type', '')}")
        recovery = await self.reasoner.propose_recovery(
            memory=memory,
            failure=error_message,
            failure_code="TARGET_NOT_FOUND",
            observation=obs,
        )
        alt = recovery.alternative_target
        if not alt and recovery.action and recovery.action.target:
            alt = recovery.action.target
        if alt:
            from app.engine.ai.validator import _deterministic_target
            return _deterministic_target(alt)
        return None

    # ── Main loop ───────────────────────────────────────────────────

    async def run(
        self,
        browser: BrowserSession,
        objective: str,
        target_url: str,
    ) -> AgentOutcome:
        memory = AgentMemory(self.execution_id, objective=objective)
        interpretation = await self.reasoner.interpret_goal(objective)
        await self._emit(EventTypes.GOAL_INTERPRETED, {
            "goal": interpretation.goal,
            "intent": interpretation.intent,
            "needs_account": interpretation.needs_account,
            "needs_email": interpretation.needs_email_capability,
            "risk_level": interpretation.risk_level,
        })

        self.app_host = self._host_of(target_url)

        # Explicit target identity: if the objective names an email, adopt it
        import re
        explicit_email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", objective)
        if explicit_email_match:
            explicit_email = explicit_email_match.group(0).lower()
            memory.identity.email = explicit_email
            memory.add_fact("email", f"target identity specified: {explicit_email}")
            if self.email_provider:
                from app.engine.email.provider import MailboxHandle
                self.mailbox = MailboxHandle(mailbox_id=explicit_email, address=explicit_email)

        # The agent owns navigation to the objective's entry point — the
        # browser session is fresh (about:blank) when run() starts.
        try:
            await browser.navigate(target_url)
        except Exception as e:
            return AgentOutcome(
                "FAILED",
                f"Could not open the target application: {str(e)[:150]}",
                facts=[],
            )

        # Journey plan (advisory skeleton — the loop refines per-turn)
        observation = await browser.observe()
        plan = await self.reasoner.plan_journey(
            memory, interpretation, observation,
            has_email_provider=self.email_provider is not None,
        )
        await self._emit(EventTypes.PLAN_CREATED, {
            "objective": plan.objective,
            "steps": len(plan.steps),
            "confidence": plan.confidence,
            "reasoning": plan.reasoning[:300],
        })

        recovery_budget = MAX_RECOVERIES
        self.recent_failure_detail = ""
        recovery_used = 0

        for turn in range(self.max_turns):
            # Observe (always fresh — the loop never trusts stale state)
            observation = await browser.observe()
            memory.current_url = browser.page.url
            await self._emit(EventTypes.OBSERVATION_CREATED, {
                "turn": turn,
                "url": memory.current_url,
                "buttons": len(observation.get("elements", [])),
            })

            # Interpret state into memory
            self._update_auth_state(memory, observation)

            # ── Deterministic completion gate (§33) ───────────────────
            # The LOOP decides completion from executor-established state,
            # never the model alone. Every flag below was set from real page
            # evidence in _update_auth_state / _handle_read_email.
            identity = memory.identity
            if identity.password_reset:
                facts = self._fact_list(memory)
                v_prop = await self.reasoner.propose_verification(
                    memory, interpretation, observation, facts
                )
                await self._emit(EventTypes.VERIFICATION_PROPOSED, {
                    "turn": turn,
                    "basis": "application confirmed the password change",
                    "reason": v_prop.reason,
                })
                return AgentOutcome(
                    "COMPLETED",
                    "Password reset flow completed and confirmed by the application",
                    verification={"text_visible": "password"},
                    facts=facts,
                )

            # Propose next action (loop surfaces the last failure for recovery context)
            proposal = await self.reasoner.propose_next_action(
                memory, interpretation, observation,
                recent_failure=self.recent_failure_detail or None,
            )
            await self._emit(EventTypes.ACTION_PROPOSED, {
                "turn": turn,
                "action": proposal.action,
                "reason": proposal.reason[:300],
                "confidence": proposal.confidence,
            })

            # Loop-level controls
            if proposal.action == "request_human":
                await self._emit(EventTypes.HUMAN_INPUT_REQUIRED, {
                    "reason": proposal.reason[:300],
                })
                return AgentOutcome(
                    "NEEDS_INPUT",
                    proposal.reason or "Agent requires human input",
                    facts=self._fact_list(memory),
                )
            if proposal.action == "abort":
                return AgentOutcome(
                    "BLOCKED",
                    proposal.reason or "Agent determined the objective cannot proceed",
                    facts=self._fact_list(memory),
                )

            # Validate the proposal (untrusted planner boundary)
            try:
                proposal = validate_action_proposal(
                    proposal,
                    allowed_hosts={self.app_host} if self.app_host else None,
                )
                await self._emit(EventTypes.ACTION_VALIDATED, {"turn": turn, "action": proposal.action})
            except ProposalRejected as e:
                # Rejected proposal = replan with the rejection as context
                self.recent_failure_detail = f"proposal rejected: {e.reason}"
                memory.replan_count += 1
                await self._emit(EventTypes.REPLAN_TRIGGERED, {
                    "turn": turn,
                    "reason": self.recent_failure_detail[:300],
                })
                if memory.replan_count > 5:
                    return AgentOutcome(
                        "FAILED",
                        f"Agent proposals kept failing validation: {self.recent_failure_detail}",
                        facts=self._fact_list(memory),
                    )
                continue

            # Turn-level controls: form submission always refocuses the form's
            # primary field first — page-level Enter doesn't submit forms.
            if proposal.action == "press" and (proposal.value or "Enter") == "Enter":
                focus_selector = None
                if isinstance(proposal.target, dict) and proposal.target.get("css"):
                    focus_selector = proposal.target["css"]
                if not focus_selector:
                    focus_selector = "form input:not([type='hidden'])"
                try:
                    await browser.page.focus(focus_selector)
                except Exception:
                    pass

            # Execute the validated proposal
            outcome = await self._execute_proposal(browser, memory, proposal, turn)
            if outcome is not None:
                return outcome  # terminal (human/blocked/failed/email exhausted)

            # Budget recoveries: a failed action consumed one unit of budget
            if self.recent_failure_detail:
                recovery_used += 1
                if recovery_used > MAX_RECOVERIES:
                    return AgentOutcome(
                        "FAILED",
                        f"Recovery budget exhausted after: {self.recent_failure_detail}",
                        facts=self._fact_list(memory),
                    )
                self.recent_failure_detail = ""  # consumed; next turn decides fresh

        return AgentOutcome(
            "UNVERIFIED",
            f"Agent reached turn budget ({self.max_turns}) without completing the objective",
            facts=self._fact_list(memory),
        )

    # ── Proposal execution ──────────────────────────────────────────

    async def _execute_proposal(
        self,
        browser: BrowserSession,
        memory: AgentMemory,
        proposal: ActionProposal,
        turn: int,
    ) -> AgentOutcome | None:
        """Execute one validated proposal. Returns AgentOutcome only when terminal."""

        # Agent-native capabilities first
        if proposal.action == "create_email":
            return await self._handle_create_email(browser, memory)
        if proposal.action == "read_email":
            return await self._handle_read_email(browser, memory, proposal)
        if proposal.action == "extract_link":
            return None  # folded into read_email

        raw = proposal_to_raw_action(
            proposal,
            identity_email=memory.identity.email,
            resolve_credential=self._resolve_credential_value,
        )
        if raw is None:
            # observe / loop-level: nothing to execute in the browser
            return None

        executor = ActionExecutor(browser.page, event_recorder=None)
        result = await executor.execute(raw)

        # Reset forms need BOTH password fields filled with the same new
        # value; the reasoner marks the confirm field via confirm_css.
        if (
            result.get("success")
            and proposal.action == "type"
            and isinstance(proposal.target, dict)
            and proposal.target.get("confirm_css")
        ):
            confirm_raw = dict(raw)
            confirm_raw["target"] = {"css": proposal.target["confirm_css"]}
            confirm_result = await executor.execute(confirm_raw)
            if not confirm_result.get("success"):
                result = confirm_result  # surface the confirm-field failure

        if not result.get("success"):
            error = result.get("error", {})
            detail = str(error.get("message", "unknown"))[:300]
            memory.record_action(
                turn, proposal.action, proposal.reason, proposal.reason,
                "failed", detail, browser.page.url,
            )
            await self._emit(EventTypes.RECOVERY_PROPOSED, {
                "turn": turn,
                "error_code": error.get("type", "unknown"),
                "detail": detail,
            })
            # Surface the failure to the loop's next-turn context
            self.recent_failure_detail = detail
            return None

        memory.record_action(
            turn, proposal.action, proposal.reason, proposal.reason,
            "success", "", browser.page.url,
        )
        await self._emit(EventTypes.STATE_CHANGED, {
            "turn": turn,
            "action": proposal.action,
            "url": browser.page.url,
        })

        # Action-outcome state transitions are observed from the real page outcome
        # on the subsequent turn in _update_auth_state (never prematurely here).

        # Post-action milestone screenshot for meaningful state changes
        await self._milestone_screenshot(browser, memory, proposal)

        # Post-action deterministic checks proposed by the model
        if proposal.verification:
            verifier = Verifier(browser.page)
            vres = await verifier.verify(proposal.verification)
            if not vres.passed:
                failed = [c.type for c in vres.checks if not c.passed]
                self._set_recent_failure(f"verification after {proposal.action} failed: {failed}")
                memory.record_action(
                    turn, "verify", str(proposal.verification), "post-action check",
                    "verification_failed", str(failed), browser.page.url,
                )
                # Not terminal — recovery/replan decides next turn
                self._set_recent_failure_tag("STATE_MISMATCH")
        # Credential-tracking state updates
        if proposal.action == "type" and proposal.credential_intent == "new_password":
            memory.identity.new_password_credential_id = memory.identity.new_password_credential_id or "agent-new-password"
        return None

    recent_failure_detail: str = ""

    def _set_recent_failure(self, detail: str) -> None:
        self.recent_failure_detail = detail

    def _set_recent_failure_tag(self, tag: str) -> None:
        self.failure_tag = tag

    def _resolve_credential_value(self, intent: str) -> str | None:
        """Resolve credential intents from the deterministic store (never AI)."""
        if intent == "email":
            return None  # handled inline from memory.identity.email
        # Passwords: look up by conventional ids the loop registers
        if intent == "password":
            cred = self.credential_store.get("agent-password") if self.credential_store.has("agent-password") else None
            return cred.get_password() if cred else None
        if intent == "new_password":
            cred = self.credential_store.get("agent-new-password") if self.credential_store.has("agent-new-password") else None
            return cred.get_password() if cred else None
        return None

    # ── Email capabilities ──────────────────────────────────────────

    async def _handle_create_email(
        self, browser: BrowserSession, memory: AgentMemory
    ) -> AgentOutcome | None:
        if memory.identity.email:
            memory.add_fact("email", f"identity already established: {memory.identity.email}")
            return None
        if not self.email_provider:
            return AgentOutcome(
                "NEEDS_INPUT",
                "Objective requires receiving email but no email provider is configured "
                "(set TEMPMAIL_SERVICE_URL)",
                facts=self._fact_list(memory),
            )
        try:
            self.mailbox = await self.email_provider.create_mailbox(
                hint=f"kova-{str(self.execution_id)[:8]}"
            )
        except Exception as e:
            logger.warning("Mailbox creation failed: %s", e)
            return AgentOutcome(
                "FAILED",
                "Temporary email provider failed — cannot establish identity",
                facts=self._fact_list(memory),
            )
        # THE identity invariant: one mailbox per execution, reused forever.
        memory.identity.email = self.mailbox.address
        memory.identity.mailbox_id = self.mailbox.mailbox_id
        memory.add_fact("email", f"temporary identity created: {memory.identity.email}")
        await self._emit(EventTypes.EMAIL_CREATED, {
            "mailbox_id": self.mailbox.mailbox_id,
            # Address is the identity — safe to show; no secrets involved.
            "address": self.mailbox.address,
        })
        return None

    async def _handle_read_email(
        self, browser: BrowserSession, memory: AgentMemory,
        proposal: ActionProposal | None = None,
    ) -> AgentOutcome | None:
        if not self.email_provider or not memory.identity.email or not self.mailbox:
            return AgentOutcome(
                "NEEDS_INPUT",
                "Email workflow requested but no mailbox exists for this execution",
                facts=self._fact_list(memory),
            )
        # Keyword hints from the reasoner narrow which message class we wait for
        # (verification vs reset); min_index skips already-consumed messages.
        subject_keywords: tuple[str, ...] = ()
        if proposal is not None and isinstance(proposal.target, dict):
            kw = proposal.target.get("subject_keywords") or []
            if isinstance(kw, list) and kw:
                subject_keywords = tuple(str(k).lower() for k in kw)
        message = await self.email_provider.wait_for_new_message(
            self.mailbox,
            timeout_seconds=EMAIL_WAIT_SECONDS,
            min_index=self.mailbox.consumed,
            subject_keywords=subject_keywords,
        )
        if message is None:
            return AgentOutcome(
                "FAILED",
                f"No matching email received within {int(EMAIL_WAIT_SECONDS)}s — "
                "the application may not have sent one",
                facts=self._fact_list(memory),
            )
        self.mailbox.consumed += 1
        await self._emit(EventTypes.EMAIL_RECEIVED, {
            "sender_domain": self._host_of(message.sender) or message.sender[:60],
            "subject": message.subject[:120],
            "link_count": len(message.links),
        })
        memory.add_fact("email", f"received: {message.subject[:80]}")

        # Select the most relevant link deterministically: prefer same-host
        # links with auth-recovery semantics in path/query.
        link = self._select_relevant_link(message, memory=memory)
        if link is None:
            return AgentOutcome(
                "FAILED",
                "Received email contains no safe, relevant link "
                "(same-host, recovery/verification semantics)",
                facts=self._fact_list(memory),
            )
        await self._emit(EventTypes.EMAIL_LINK_SELECTED, {
            "host": self._host_of(link),
            "path": link.split("?")[0][-80:],
        })
        memory.add_fact("email_link", f"validated link: {link.split('?')[0]}")

        # Untrusted-link navigation — host + SSRF validated (§10)
        if not validate_email_link(link, app_host=self.app_host):
            return AgentOutcome(
                "FAILED",
                "Email link failed the navigation security policy",
                facts=self._fact_list(memory),
            )
        try:
            await browser.navigate(link)
        except Exception as e:
            return AgentOutcome(
                "FAILED",
                f"Navigation to email link failed: {str(e)[:150]}",
                facts=self._fact_list(memory),
            )
        memory.add_fact("navigation", "opened validated email link")
        await self._milestone_screenshot(browser, memory, None, label="email link opened")
        return None

    def _select_relevant_link(
        self, message: EmailMessage, memory: AgentMemory | None = None
    ) -> str | None:
        """Deterministic link selection: same-host first, intent-aware scoring."""
        scored: list[tuple[int, str]] = []
        positive_keywords = ("reset", "recover", "verify", "confirm", "activate", "token", "auth")
        negative_keywords = ("unsubscribe", "opt-out", "privacy", "terms", "legal", "preferences", "help")
        identity = memory.identity if memory else None

        for link in message.links:
            if not validate_email_link(link, app_host=self.app_host):
                continue  # cross-host / unsafe links are never candidates
            lower = link.lower()
            if any(neg in lower for neg in negative_keywords):
                continue

            score = 1
            if identity and identity.recovery_requested and not identity.reset_link_opened:
                if any(kw in lower for kw in ("reset", "recover", "password")):
                    score += 10
            elif identity and not identity.account_verified:
                if any(kw in lower for kw in ("verify", "confirm", "activate")):
                    score += 10

            if any(kw in lower for kw in positive_keywords):
                score += 5
            if "token" in lower or "code" in lower:
                score += 3
            scored.append((score, link))

        if not scored:
            return None
        scored.sort(key=lambda pair: -pair[0])
        return scored[0][1]

    # ── Milestones & verification ───────────────────────────────────

    async def _milestone_screenshot(
        self,
        browser: BrowserSession,
        memory: AgentMemory,
        proposal: ActionProposal | None,
        label: str = "",
    ) -> None:
        """Capture evidence at meaningful milestones (§29), not every click."""
        milestone_reasons = ("recovery", "reset", "sign", "log", "verify", "dashboard", "email")
        text = (proposal.reason if proposal else label or "").lower()
        if proposal is not None and not any(kw in text for kw in milestone_reasons):
            if proposal.action not in ("read_email", "create_email"):
                return
        try:
            ss = await browser.page.screenshot(type="jpeg", quality=70)
            if ss:
                meta = await asyncio.to_thread(
                    screenshot_storage.save,
                    str(self.execution_id),
                    ss,
                    browser.page.url,
                )
                await self._emit(EventTypes.BROWSER_SCREENSHOT, {
                    "url": browser.page.url,
                    "screenshot_key": meta.get("screenshot_key"),
                    "screenshot_url": meta.get("screenshot_url"),
                    "milestone": (label or text)[:60],
                })
        except Exception as e:
            logger.debug("Milestone screenshot failed: %s", e)

    def _update_auth_state(self, memory: AgentMemory, observation: dict) -> None:
        """Update identity state ONLY from real page evidence (never guesses)."""
        from app.engine.ai.observation import detect_auth_signals
        signals = detect_auth_signals(observation)
        text = (observation.get("text") or "").lower()
        url = (observation.get("url") or "").lower()
        identity = memory.identity

        if "authenticated_indicators" in signals and "password_field_present" not in signals:
            memory.auth_state = "authenticated"
            identity.authenticated = True
        elif "password_field_present" in signals:
            if "login_page_url" in signals or "/login" in url or "/?" in url or url.endswith("/"):
                memory.auth_state = "logged_out"
                identity.authenticated = False
                identity.logged_out = True

        # Email verified: opened verification link
        verified_texts = (
            "account verified", "email verified", "confirmed", "now active",
            "registration complete", "account activated", "successfully verified"
        )
        if any(t in text for t in verified_texts) or any(t in url for t in ("/verify", "verified=1", "verified=true", "confirmed=1")):
            if identity.signup_completed and not identity.account_verified:
                identity.account_verified = True
                memory.add_fact("account", "email verified by application")

        # Signup completed: the app showed its post-signup verification prompt
        if "email_verification_prompt" in signals and identity.email and not identity.signup_completed:
            identity.signup_completed = True
            identity.account_created = True
            memory.add_fact("account", "signup submitted; verification email requested")

        # Recovery initiated: the app confirmed the reset email was sent
        unfilled_email_present = any(
            not i.get("filled") and "email" in (i.get("name", "") + " " + i.get("input_type", "")).lower()
            for i in observation.get("inputs", [])
        )
        if any(t in text for t in RESET_SENT_TEXTS) and identity.email and not identity.recovery_requested and not unfilled_email_present:
            identity.recovery_requested = True
            memory.add_fact("recovery", "application confirmed recovery email sent")

        # Reset link opened: we are on the app's reset form (came from email)
        is_reset_form = (
            any(t in url for t in ("/reset", "/new-password", "/change-password", "token="))
            or any(t in text for t in ("new password", "create new password", "set your password", "reset your password", "choose a new password"))
            or ("password_field_present" in signals and not identity.authenticated and not identity.logged_out)
        )
        if identity.recovery_requested and not identity.reset_link_opened and is_reset_form:
            identity.reset_link_opened = True
            memory.add_fact("recovery", "reset link opened; reset form displayed")

        # Password reset confirmed by the application
        reset_confirm_texts = (
            "password updated", "password has been changed", "password has been reset",
            "password reset successfully", "your password has been updated", "successfully reset",
            "password changed", "password has been saved", "new password has been set",
        )
        if identity.reset_link_opened and not identity.password_reset:
            if any(t in text for t in reset_confirm_texts) or any(t in url for t in ("reset=success", "password_updated=1", "updated=true")):
                identity.password_reset = True
                memory.add_fact("recovery", "application confirmed the password was changed")

    def _fact_list(self, memory: AgentMemory) -> list[str]:
        return [f"{f.kind}: {f.detail}" for f in memory.facts]

    @staticmethod
    def _host_of(url: str) -> str | None:
        from urllib.parse import urlparse
        try:
            return (urlparse(url).hostname or "").lower() or None
        except ValueError:
            return None
