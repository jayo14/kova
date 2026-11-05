"""Tests for intelligent interface obstruction handling, temporal reasoning, and transient recovery."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.engine.exploration.agent.interruption import (
    InterruptionDecision,
    InterruptionEvaluator,
    InterruptionType,
)
from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction
from app.engine.exploration.agent.temporal import (
    OperationOutcomeStatus,
    TemporalEvaluator,
)
from app.engine.exploration.agent.understanding import (
    ApplicationUnderstanding,
    DependencyState,
    SessionAuthState,
)
from app.engine.exploration.agent.epistemic_agent import EpistemicExplorationAgent


# ============================================================================
# 1. Interface Obstruction & Modal Handling Tests
# ============================================================================

def test_install_app_modal_detected_and_dismissed():
    """Verifies that an optional PWA/install app modal (like Log2Def) is identified as optional and dismissed."""
    dialog = {
        "title": "Install Log2Def App",
        "accessible_name": "Install Log2Def App",
        "description": "Install Log2Def as a standalone desktop app on your computer.",
        "role": "dialog",
        "is_modal": True,
        "aria_modal": True,
        "is_obstructing": True,
        "can_dismiss": True,
        "text": "Install Log2Def as a standalone desktop app on your computer.\nGot it",
        "buttons": [
            {"name": "Got it", "text": "Got it", "role": "button", "selector": "button:has-text('Got it')"}
        ],
        "inputs": [],
        "selector": "div[aria-label='Install Log2Def']",
    }
    understanding = ApplicationUnderstanding(target_url="https://log2def.vercel.app/dashboard")
    understanding.is_currently_authenticated = True

    analysis = InterruptionEvaluator.evaluate(dialog, {"url": "https://log2def.vercel.app/dashboard"}, understanding)

    assert analysis.interruption_type == InterruptionType.OPTIONAL_PROMPT
    assert analysis.decision == InterruptionDecision.DISMISS
    assert analysis.can_dismiss is True
    assert analysis.dismiss_control is not None
    assert analysis.dismiss_control["text"] == "Got it"
    assert "optional" in analysis.reason.lower()

    prop = InterruptionEvaluator.propose_action_for_interruption(analysis, dialog, "node-dashboard")
    assert prop is not None
    assert prop.action == ExplorationAction.DISMISS_INTERRUPTION
    assert prop.target.get("text") == "Got it"


def test_promotional_modal_dismissal():
    """Verifies optional promotional announcement modals are dismissed."""
    dialog = {
        "title": "What's New in v2.4",
        "accessible_name": "What's New in v2.4",
        "role": "dialog",
        "is_modal": True,
        "can_dismiss": True,
        "text": "Check out our newest reporting features and analytics.\nDismiss",
        "buttons": [
            {"name": "Dismiss", "text": "Dismiss", "role": "button", "selector": "button:has-text('Dismiss')"}
        ],
        "inputs": [],
    }
    understanding = ApplicationUnderstanding(target_url="https://example.com/app")
    analysis = InterruptionEvaluator.evaluate(dialog, {}, understanding)

    assert analysis.interruption_type == InterruptionType.OPTIONAL_PROMPT
    assert analysis.decision == InterruptionDecision.DISMISS
    assert analysis.dismiss_control["name"] == "Dismiss"


def test_permission_request_makes_informed_choice():
    """Verifies permission requests choose non-invasive decline instead of blindly accepting."""
    dialog = {
        "title": "Enable Desktop Notifications",
        "accessible_name": "Enable Desktop Notifications",
        "role": "alertdialog",
        "is_modal": True,
        "can_dismiss": True,
        "text": "Get notified when reports are generated.\nAllow\nNot now",
        "buttons": [
            {"name": "Allow", "text": "Allow", "role": "button", "selector": "button:has-text('Allow')"},
            {"name": "Not now", "text": "Not now", "role": "button", "selector": "button:has-text('Not now')"},
        ],
        "inputs": [],
    }
    understanding = ApplicationUnderstanding(target_url="https://example.com/dashboard")
    analysis = InterruptionEvaluator.evaluate(dialog, {}, understanding)

    assert analysis.interruption_type == InterruptionType.PERMISSION_REQUEST
    assert analysis.decision == InterruptionDecision.MAKE_INFORMED_CHOICE
    # Prefers "Not now" or decline over "Allow"
    assert analysis.action_control is not None
    assert analysis.action_control["name"] == "Not now"


def test_required_setup_onboarding_wizard():
    """Verifies required onboarding/workspace setup is completed with safe synthetic test data."""
    dialog = {
        "title": "Create your Workspace",
        "accessible_name": "Create your Workspace",
        "role": "dialog",
        "is_modal": True,
        "can_dismiss": False,
        "text": "Name your workspace to begin exploring.\nWorkspace Name: [     ]\nContinue",
        "buttons": [
            {"name": "Continue", "text": "Continue", "role": "button", "selector": "button:has-text('Continue')"}
        ],
        "inputs": [
            {"name": "workspace_name", "label": "Workspace Name", "type": "text", "required": True, "selector": "#ws-name"}
        ],
    }
    understanding = ApplicationUnderstanding(target_url="https://example.com/onboarding")
    analysis = InterruptionEvaluator.evaluate(dialog, {}, understanding)

    assert analysis.interruption_type == InterruptionType.REQUIRED_SETUP
    assert analysis.decision == InterruptionDecision.COMPLETE_REQUIRED
    assert analysis.fields_to_fill.get("#ws-name") == "Kova Test Workspace"
    assert analysis.action_control["name"] == "Continue"

    prop = InterruptionEvaluator.propose_action_for_interruption(analysis, dialog, "node-onboarding")
    assert prop is not None
    assert prop.action == ExplorationAction.COMPLETE_INTERRUPTION
    assert "#ws-name" in prop.target.get("fields", {})


def test_consequential_billing_modal_requests_human_assistance():
    """Verifies consequential payment or sensitive requests trigger request_assistance."""
    dialog = {
        "title": "Enter Credit Card Details",
        "accessible_name": "Payment Required",
        "role": "dialog",
        "is_modal": True,
        "can_dismiss": False,
        "text": "Enter billing credit card number to activate account.",
        "buttons": [{"name": "Pay Now", "text": "Pay Now", "role": "button", "selector": "#pay-btn"}],
        "inputs": [{"name": "card_number", "type": "text", "required": True, "selector": "#card"}],
    }
    understanding = ApplicationUnderstanding(target_url="https://example.com/billing")
    analysis = InterruptionEvaluator.evaluate(dialog, {}, understanding)

    assert analysis.decision == InterruptionDecision.REQUEST_ASSISTANCE
    assert "sensitive" in analysis.reason.lower() or "consequential" in analysis.reason.lower()


def test_non_modal_banner_is_preserved_and_deferred():
    """Verifies non-modal, non-obstructing banners are preserved without halting page exploration."""
    dialog = {
        "title": "Maintenance Notice",
        "role": "banner",
        "is_modal": False,
        "is_obstructing": False,
        "can_dismiss": False,
        "text": "Scheduled maintenance on Sunday at 2 AM UTC.",
        "buttons": [],
        "inputs": [],
    }
    understanding = ApplicationUnderstanding(target_url="https://example.com/dashboard")
    analysis = InterruptionEvaluator.evaluate(dialog, {}, understanding)

    assert analysis.decision == InterruptionDecision.PRESERVE_AND_DEFER
    prop = InterruptionEvaluator.propose_action_for_interruption(analysis, dialog, "node-dashboard")
    assert prop is None  # Does not block standard exploration


# ============================================================================
# 2. Session State Model & Login Verification Loop Prevention Tests
# ============================================================================

def test_session_state_transitions():
    """Verifies session state transitions cleanly without false regressions."""
    und = ApplicationUnderstanding(target_url="https://log2def.vercel.app")
    assert und.session_state == SessionAuthState.AUTHENTICATION_STATE_UNCERTAIN
    assert und.is_currently_authenticated is False

    # Auth in progress
    und.update_session_auth(SessionAuthState.AUTHENTICATION_IN_PROGRESS)
    assert und.session_state == SessionAuthState.AUTHENTICATION_IN_PROGRESS

    # Auth successful
    und.update_session_auth(SessionAuthState.AUTHENTICATION_SUCCESSFUL)
    assert und.is_currently_authenticated is True

    # Maintained
    und.update_session_auth(SessionAuthState.AUTHENTICATED_SESSION_MAINTAINED)
    assert und.is_currently_authenticated is True

    # Genuine loss
    und.update_session_auth(SessionAuthState.AUTHENTICATION_GENUINELY_LOST)
    assert und.is_currently_authenticated is False


@pytest.mark.asyncio
async def test_agent_does_not_navigate_to_login_when_authenticated():
    """Critical Log2Def regression test: When authenticated at /dashboard, BFS must NOT propose /login."""
    page = AsyncMock()
    page.url = "https://log2def.vercel.app/dashboard"
    agent = EpistemicExplorationAgent(engine=MagicMock(), page=page)
    agent.understanding.is_currently_authenticated = True
    agent.understanding.update_session_auth(SessionAuthState.AUTHENTICATED_SESSION_MAINTAINED)

    node = agent.sitemap.get_or_create_node(page.url)

    observation = {
        "url": "https://log2def.vercel.app/dashboard",
        "title": "Dashboard",
        "links": [
            {"name": "Sign In", "href": "https://log2def.vercel.app/login", "selector": "#login-link"},
            {"name": "Reports", "href": "https://log2def.vercel.app/dashboard/reports", "selector": "#reports-link"},
            {"name": "Settings", "href": "https://log2def.vercel.app/dashboard/settings", "selector": "#settings-link"},
        ],
        "controls": [],
        "dialogs": [],
    }

    proposal = await agent._propose(observation, node)
    assert proposal is not None
    # Must propose functional app links (Reports/Settings), NEVER Sign In / login!
    target_url = proposal.target.get("url") or proposal.target.get("href")
    assert "/login" not in str(target_url).lower()
    assert "/dashboard/reports" in str(target_url) or "/dashboard/settings" in str(target_url)


# ============================================================================
# 3. Temporal Reasoning & Transient Failure Recovery Tests (Quiza Case)
# ============================================================================

def test_temporal_outcome_classification_transient_blocked():
    """Verifies that an active pending host (Render cold start) evaluates to TRANSIENTLY_BLOCKED, not FAILED."""
    prop = AgentActionProposal(
        action=ExplorationAction.AUTHENTICATE,
        target={"url": "https://quiza-ai.vercel.app/signup", "is_signup": True},
        reason="submit registration",
    )
    before_obs = {"url": "https://quiza-ai.vercel.app/signup", "text": "Sign Up"}
    after_obs = {"url": "https://quiza-ai.vercel.app/signup", "text": "Sign Up", "alerts": []}
    und = ApplicationUnderstanding(target_url="https://quiza-ai.vercel.app")

    # Render cold start pending 4s
    pending_host = ("quiza-urmm.onrender.com", 4.0)

    eval_res = TemporalEvaluator.evaluate_operation(prop, before_obs, after_obs, und, pending_host=pending_host)

    assert eval_res.status == OperationOutcomeStatus.TRANSIENTLY_BLOCKED
    assert eval_res.is_transient is True
    assert eval_res.affected_dependency == "quiza-urmm.onrender.com"
    assert und.dependencies["quiza-urmm.onrender.com"].is_ready is False


def test_temporal_outcome_classification_inconclusive():
    """Verifies that remaining on /signup without error message or redirect is INCONCLUSIVE, not FAILED."""
    prop = AgentActionProposal(
        action=ExplorationAction.AUTHENTICATE,
        target={"url": "https://quiza-ai.vercel.app/signup", "is_signup": True},
        reason="submit registration",
    )
    before_obs = {"url": "https://quiza-ai.vercel.app/signup"}
    after_obs = {"url": "https://quiza-ai.vercel.app/signup", "alerts": [], "text": "Quiza Sign Up Form"}
    und = ApplicationUnderstanding(target_url="https://quiza-ai.vercel.app")

    eval_res = TemporalEvaluator.evaluate_operation(prop, before_obs, after_obs, und, pending_host=None)

    assert eval_res.status == OperationOutcomeStatus.INCONCLUSIVE
    assert eval_res.is_transient is True
    assert eval_res.retry_safe is False  # Must NOT blindly retry with duplicate new credentials


def test_temporal_outcome_classification_auth_redirect_pending():
    """Verifies Supabase authorization redirect in flight evaluates to PENDING."""
    prop = AgentActionProposal(
        action=ExplorationAction.AUTHENTICATE,
        target={"url": "https://quiza-ai.vercel.app/signup", "is_signup": True},
        reason="submit registration",
    )
    before_obs = {"url": "https://quiza-ai.vercel.app/signup"}
    after_obs = {"url": "https://supabase.co/auth/v1/authorize?provider=google", "alerts": []}
    und = ApplicationUnderstanding(target_url="https://quiza-ai.vercel.app")

    eval_res = TemporalEvaluator.evaluate_operation(prop, before_obs, after_obs, und)

    assert eval_res.status == OperationOutcomeStatus.PENDING
    assert eval_res.is_transient is True


def test_retry_safety_prevents_duplicate_registration_attempts():
    """Verifies that Kova does not repeatedly create accounts with different credentials."""
    und = ApplicationUnderstanding(target_url="https://quiza-ai.vercel.app")
    und.attempted_auth_strategies.append({
        "type": "self_registration",
        "provider": None,
        "success": False,
        "outcome": "Inconclusive (remained at /signup)",
    })
    und.attempted_auth_strategies.append({
        "type": "self_registration",
        "provider": None,
        "success": False,
        "outcome": "Inconclusive (remained at /signup)",
    })

    prop = AgentActionProposal(
        action=ExplorationAction.AUTHENTICATE,
        target={"url": "https://quiza-ai.vercel.app/signup", "is_signup": True},
    )
    safe, reason = TemporalEvaluator.evaluate_retry_safety(prop, und)
    assert safe is False
    assert "duplicate" in reason.lower()
