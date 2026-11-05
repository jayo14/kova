"""Temporal reasoning and transient failure recovery for autonomous exploration.

Enables Kova to reason about time-dependent application behavior:
- Distinguishes Succeeded, Failed, Pending, Transiently Blocked, Inconclusive, and Requires Assistance.
- Tracks infrastructure dependencies across time (e.g. Render cold starts, delayed backend APIs).
- Implements evidence-driven adaptive waiting and safe, bounded recovery loops.
- Prevents premature termination while meaningful exploration is pending.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from urllib.parse import urlparse

from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction
from app.engine.exploration.agent.understanding import ApplicationUnderstanding, SessionAuthState

logger = logging.getLogger(__name__)


class OperationOutcomeStatus(str, Enum):
    """Epistemic classification of an interaction outcome."""
    SUCCEEDED = "succeeded"                     # Established through affirmative evidence
    FAILED = "failed"                           # Sufficient evidence that the operation did not succeed
    PENDING = "pending"                         # Operation or redirect is still processing in background
    TRANSIENTLY_BLOCKED = "transiently_blocked" # Temporary dependency (cold start, warming backend, rate limit)
    INCONCLUSIVE = "inconclusive"               # Available evidence does not establish success or failure
    REQUIRES_ASSISTANCE = "requires_assistance" # Consequential human step required


@dataclass
class OperationEvaluation:
    """Detailed evaluation of an action outcome with temporal recommendations."""
    status: OperationOutcomeStatus
    reason: str
    is_transient: bool = False
    retry_safe: bool = True
    suggested_wait_s: float = 0.0
    needs_reobservation: bool = False
    affected_dependency: str | None = None
    event_description: str = ""


class TemporalEvaluator:
    """Evaluates time-dependent application conditions and guides adaptive investigation."""

    @staticmethod
    def evaluate_operation(
        proposal: AgentActionProposal,
        before_obs: dict[str, Any],
        after_obs: dict[str, Any],
        understanding: ApplicationUnderstanding,
        pending_host: tuple[str, float] | None = None,  # (host, pending_age_s)
    ) -> OperationEvaluation:
        """Categorizes action outcome into SUCCEEDED, FAILED, PENDING, TRANSIENTLY_BLOCKED, or INCONCLUSIVE."""
        before_url = str(before_obs.get("url") or "")
        after_url = str(after_obs.get("url") or "")
        before_path = urlparse(before_url).path.lower()
        after_path = urlparse(after_url).path.lower()

        # Check for active pending infrastructure dependencies
        if pending_host:
            host_name, pending_age = pending_host
            understanding.update_dependency(
                host=host_name,
                is_ready=False,
                status="warming_up",
                pending_duration=pending_age,
            )
            return OperationEvaluation(
                status=OperationOutcomeStatus.TRANSIENTLY_BLOCKED,
                reason=f"Application dependency '{host_name}' is initializing / warming up (pending {int(pending_age)}s).",
                is_transient=True,
                retry_safe=False,
                suggested_wait_s=min(15.0, max(3.0, 30.0 - pending_age)),
                needs_reobservation=True,
                affected_dependency=host_name,
                event_description=f"Detected backend initialization: waiting on {host_name} (pending {int(pending_age)}s)",
            )

        # Evaluate Authentication / Registration Submissions
        is_auth_action = (
            proposal.action == ExplorationAction.AUTHENTICATE
            or proposal.source == "auth_strategy_evaluator"
            or any(k in before_path for k in ("/login", "/signin", "/sign-in", "/register", "/signup", "/sign-up"))
        )

        if is_auth_action:
            # Check for redirect to Supabase / OAuth auth endpoints
            if any(k in after_url.lower() for k in ("/auth/v1/authorize", "supabase.co/auth", "accounts.google.com", "github.com/login/oauth")):
                return OperationEvaluation(
                    status=OperationOutcomeStatus.PENDING,
                    reason=f"Authentication redirect in flight to identity provider ({after_url}).",
                    is_transient=True,
                    retry_safe=False,
                    suggested_wait_s=5.0,
                    needs_reobservation=True,
                    event_description=f"Authentication redirect in progress: {urlparse(after_url).netloc}",
                )

            # Check affirmative success
            is_after_auth_area = any(p in after_path for p in ("/login", "/register", "/signup", "/signin", "/sign-in", "/auth"))
            is_workspace = any(k in after_path for k in ("/dashboard", "/workspace", "/app", "/console", "/home", "/account"))
            if not is_after_auth_area and (is_workspace or understanding.is_currently_authenticated):
                return OperationEvaluation(
                    status=OperationOutcomeStatus.SUCCEEDED,
                    reason=f"Application workspace reached at {after_url}.",
                    is_transient=False,
                    retry_safe=False,
                    event_description=f"Application access verified: Successfully entered application workspace at {after_url}",
                )

            # Check explicit error messages or alerts
            alerts = after_obs.get("alerts") or []
            visible_text = str(after_obs.get("text") or "").lower()
            error_keywords = [
                "invalid credentials", "incorrect password", "user not found",
                "already registered", "already exists", "email taken",
                "password too short", "passwords do not match", "rate limit",
            ]
            found_error = None
            for alert in alerts:
                if any(k in alert.lower() for k in error_keywords):
                    found_error = alert
                    break
            if not found_error:
                for kw in error_keywords:
                    if kw in visible_text:
                        found_error = kw
                        break

            if found_error:
                return OperationEvaluation(
                    status=OperationOutcomeStatus.FAILED,
                    reason=f"Explicit authentication error observed: '{found_error}'.",
                    is_transient=False,
                    retry_safe=True,
                    event_description=f"Authentication attempt failed with error: {found_error}",
                )

            # Remained on signup/login with no error and no redirect
            if is_after_auth_area and before_path == after_path:
                return OperationEvaluation(
                    status=OperationOutcomeStatus.INCONCLUSIVE,
                    reason=f"Remained on authentication view ({after_url}) without error banner or successful redirect.",
                    is_transient=True,
                    retry_safe=False,  # Unsafe to blindly retry with new credentials
                    suggested_wait_s=3.0,
                    needs_reobservation=True,
                    event_description=f"Authentication outcome inconclusive at {after_url}; awaiting state settlement",
                )

        # Standard navigation/action
        if after_url != before_url:
            return OperationEvaluation(
                status=OperationOutcomeStatus.SUCCEEDED,
                reason=f"Navigated to {after_url}.",
                is_transient=False,
            )

        return OperationEvaluation(
            status=OperationOutcomeStatus.SUCCEEDED,
            reason="Action completed on current page.",
            is_transient=False,
        )

    @staticmethod
    def evaluate_retry_safety(
        proposal: AgentActionProposal,
        understanding: ApplicationUnderstanding,
    ) -> tuple[bool, str]:
        """Ensures that retrying an inconclusive action is safe and does not produce duplicate state."""
        target = proposal.target or {}
        is_signup = target.get("is_signup") or "signup" in str(target.get("url") or "").lower() or "register" in str(target.get("url") or "").lower()

        if is_signup:
            signup_attempts = [
                att for att in understanding.attempted_auth_strategies
                if att.get("type") == "self_registration"
            ]
            if len(signup_attempts) >= 2:
                return False, "Registration already attempted; avoiding duplicate synthetic account generation."

            inconclusive = any(not att.get("success") and "inconclusive" in str(att.get("outcome") or "").lower() for att in signup_attempts)
            if inconclusive:
                return True, "Previous attempt was inconclusive; verifying if account was created."

        return True, "Action is safe to execute."

    @staticmethod
    async def adaptively_wait_for_settlement(
        page: Any,
        pending_checker: Callable[[], tuple[str, float] | None] | None = None,
        max_wait_s: float = 12.0,
        poll_interval_s: float = 0.5,
    ) -> dict[str, Any]:
        """Adaptively waits for in-flight requests, pending backends, or client-side redirects."""
        start_time = time.monotonic()
        last_url = getattr(page, "url", "")
        settled = False

        while (time.monotonic() - start_time) < max_wait_s:
            await asyncio.sleep(poll_interval_s)

            current_url = getattr(page, "url", "")
            if current_url != last_url:
                settled = True
                break

            if pending_checker:
                pending = pending_checker()
                if not pending:
                    settled = True
                    break

        elapsed = round(time.monotonic() - start_time, 2)
        return {
            "settled": settled,
            "elapsed_s": elapsed,
            "final_url": getattr(page, "url", last_url),
        }
