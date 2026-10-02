"""Comprehensive robustness, adversarial variants, blind objectives, and security red-team tests.

Validates that Kova operates as a genuinely intelligent agent across:
- Adversarial 2nd-generation UI variants (D, G, I, J, M)
- Blind objective variations (different phrasing, intent structures)
- Security red-team challenges (SSRF link injection, cross-host rejection, credential safety)
- Verification integrity (fail-closed completion gate, human handoff triggers)
"""

import asyncio
import socket
import time
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.ai.executor import AgentExecutor, AgentOutcome
from app.engine.ai.memory import AgentMemory
from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import GoalInterpretation
from app.engine.browser.session import BrowserSession
from app.engine.credentials.models import Credential
from app.engine.credentials.store import CredentialStore
from app.engine.email.provider import (
    EmailMessage,
    HTTPPollMailboxProvider,
    validate_email_link,
)
from tests.agent_fixture import (
    ACCOUNTS,
    MAILBOXES,
    agent_app,
    mail_service,
    seed_account,
)


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_app(app, log_level: str = "error"):
    port = _get_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level=log_level)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.4)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def fixture_env():
    """Starts agent app + mail service."""
    import tests.agent_fixture as fx

    fx.ACCOUNTS.clear()
    fx.PENDING_VERIFICATION.clear()
    fx.RESET_TOKENS.clear()
    fx.SESSIONS.clear()
    fx.MAILBOXES.clear()

    async with _run_app(agent_app) as app_url, _run_app(mail_service) as mail_url:
        original_app_port = fx.APP_PORT
        fx.APP_PORT = int(app_url.split(":")[2])
        yield app_url, mail_url, fx
        fx.APP_PORT = original_app_port
        fx.ACCOUNTS.clear()
        fx.PENDING_VERIFICATION.clear()
        fx.RESET_TOKENS.clear()
        fx.SESSIONS.clear()
        fx.MAILBOXES.clear()


@pytest.fixture
def agent_credential_store():
    store = CredentialStore()
    store.add(Credential(id="agent-password", email="", password="OriginalPass123!"))
    store.add(Credential(id="agent-new-password", email="", password="NewPassword456!"))
    return store


def _make_executor(mail_url: str, cred_store) -> AgentExecutor:
    provider = HTTPPollMailboxProvider(base_url=mail_url)
    return AgentExecutor(
        execution_id=uuid.uuid4(),
        reasoner=AgentReasoner(provider=None),
        email_provider=provider,
        credential_store=cred_store,
        event_emitter=None,
    )


# ── 1. 2nd-Generation Adversarial Variants ───────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["d", "g", "i", "j", "m"])
async def test_adversarial_variants_benchmark(fixture_env, agent_credential_store, variant):
    """Proves adaptability across adversarial 2nd-gen variants (D, G, I, J, M)."""
    app_url, mail_url, _ = fixture_env
    executor = _make_executor(mail_url, agent_credential_store)

    objective = (
        "Test the forgot password functionality. If the account does not exist, "
        "create one using a temporary email address, log out, then use that same "
        "email address to test the forgot password flow."
    )

    async with BrowserSession() as browser:
        await browser.navigate(f"{app_url}/?v={variant}")
        outcome = await executor.run(
            browser,
            objective=objective,
            target_url=f"{app_url}/?v={variant}",
        )

    assert outcome.status in ("COMPLETED", "UNVERIFIED"), outcome.to_dict()
    assert executor.mailbox is not None
    assert executor.mailbox.address in " ".join(outcome.facts)

    account = ACCOUNTS.get(executor.mailbox.address.lower())
    assert account is not None
    assert account["verified"] is True
    assert account["password"] == "NewPassword456!"


# ── 2. Blind Objective Tests ─────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "objective",
    [
        "Verify user can recover their account password when forgotten.",
        "Validate the account password recovery journey end-to-end.",
        "Ensure password reset works seamlessly for a registered user using a temporary mailbox.",
    ],
)
async def test_blind_objective_interpretation(fixture_env, agent_credential_store, objective):
    """Proves the agent interprets varied natural language goals without exact wording."""
    app_url, mail_url, _ = fixture_env
    executor = _make_executor(mail_url, agent_credential_store)

    interpretation = await executor.reasoner.interpret_goal(objective)
    assert interpretation.intent in ("forgot_password", "auth_recovery", "form_journey", "explore")
    assert interpretation.needs_email_capability is True

    async with BrowserSession() as browser:
        await browser.navigate(f"{app_url}/?v=a")
        outcome = await executor.run(
            browser,
            objective=objective,
            target_url=f"{app_url}/?v=a",
        )

    assert outcome.status in ("COMPLETED", "UNVERIFIED")


# ── 3. Security Red-Team Tests ───────────────────────────────────────


def test_ssrf_malicious_email_link_rejection():
    """Security Gate: Malicious/SSRF email links are rejected before browser navigation."""
    app_host = "127.0.0.1:8300"

    # Cloud metadata SSRF attempt
    assert validate_email_link("http://169.254.169.254/latest/meta-data", app_host=app_host) is False

    # External phishing/redirect attempt
    assert validate_email_link("https://attacker-controlled.com/reset?token=abc", app_host=app_host) is False

    # JavaScript URI attempt
    assert validate_email_link("javascript:alert(1)", app_host=app_host) is False

    # File URI attempt
    assert validate_email_link("file:///etc/passwd", app_host=app_host) is False

    # Legitimate app host match
    assert validate_email_link("http://127.0.0.1:8300/reset?token=abc", app_host=app_host) is True


def test_subdomain_navigation_policy():
    """Subdomain validation allows trusted app subdomains while rejecting external hosts."""
    app_host = "example.com"
    assert validate_email_link("https://auth.example.com/reset", app_host=app_host) is True
    assert validate_email_link("https://notexample.com/reset", app_host=app_host) is False
    assert validate_email_link("https://example.com.attacker.com/reset", app_host=app_host) is False


def test_credential_leak_prevention(agent_credential_store):
    """Memory and event streams must never leak raw credential passwords."""
    memory = AgentMemory(
        execution_id=uuid.uuid4(),
        objective="Test password recovery",
    )
    memory.identity.email = "test@example.com"
    memory.identity.password_credential_id = "agent-password"
    memory.identity.new_password_credential_id = "agent-new-password"

    safe_dict = memory.identity.to_safe_dict()
    assert "OriginalPass123!" not in str(safe_dict)
    assert "NewPassword456!" not in str(safe_dict)
    assert safe_dict["has_password_ref"] is True
    assert safe_dict["has_new_password_ref"] is True


# ── 4. Verification Integrity Tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_verification_gate_requires_facts():
    """Verification proposal must fail closed if required facts are absent."""
    reasoner = AgentReasoner(provider=None)
    memory = AgentMemory(execution_id=uuid.uuid4(), objective="Test password reset")
    interpretation = GoalInterpretation(
        goal="Test password reset",
        domain="authentication",
        intent="auth_recovery",
        success_requirements=["password changed", "email verified"],
        needs_email_capability=True,
    )

    # Empty facts -> UNVERIFIED
    v_empty = await reasoner.propose_verification(memory, interpretation, {}, [])
    assert v_empty.intent_satisfied is False

    # Partial facts -> UNVERIFIED
    v_partial = await reasoner.propose_verification(memory, interpretation, {}, ["email verified"])
    assert v_partial.intent_satisfied is False

    # Complete facts -> Intent satisfied
    v_complete = await reasoner.propose_verification(
        memory, interpretation, {}, ["email verified", "application confirmed the password was changed"]
    )
    assert v_complete.intent_satisfied is True


@pytest.mark.asyncio
async def test_multi_link_scoring_and_distractor_filtering():
    """Executor correctly filters unsubscribe/privacy distractors in multi-link emails."""
    executor = AgentExecutor(
        execution_id=uuid.uuid4(),
        reasoner=AgentReasoner(provider=None),
        email_provider=None,
    )
    executor.app_host = "example.com"
    memory = AgentMemory(execution_id=uuid.uuid4(), objective="Test recovery")
    memory.identity.recovery_requested = True

    msg = EmailMessage(
        sender="security@example.com",
        subject="Reset your password",
        body_text="Links below",
        links=[
            "https://example.com/privacy",
            "https://example.com/unsubscribe?user=1",
            "https://example.com/reset-password?token=safe123",
            "https://example.com/terms",
        ],
    )

    chosen = executor._select_relevant_link(msg, memory=memory)
    assert chosen == "https://example.com/reset-password?token=safe123"
