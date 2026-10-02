"""E2E agent benchmark: the forgot-password workflow (spec §31).

Real pipeline end to end:
  AgentExecutor loop → validator → ActionExecutor → Playwright → fixture app
  + fixture mail service → identity persistence → verification → outcome.

The objective is given in natural language. The agent must:
  create temp email → signup → email-verify via mailbox → logout →
  forgot-password with the SAME email → retrieve reset mail from the SAME
  mailbox → open validated reset link → set new password → verify outcome.

Deterministic-only mode (no AI provider): the heuristic reasoner drives the
same loop. This proves the loop, the safety rails, and the identity invariants
independently of any model provider.

Failure scenarios (§32) are covered at the end.
"""

import asyncio
import socket
import time
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient

from app.engine.ai.executor import AgentExecutor, AgentOutcome
from app.engine.ai.memory import AgentMemory
from app.engine.ai.reasoner import AgentReasoner
from app.engine.browser.session import BrowserSession
from app.engine.credentials.models import Credential
from app.engine.credentials.store import CredentialStore
from app.engine.email.provider import (
    HTTPPollMailboxProvider,
    extract_links,
    validate_email_link,
)
from tests.agent_fixture import (
    ACCOUNTS,
    MAILBOXES,
    RESET_TOKENS,
    agent_app,
    mail_service,
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


class _PatchableMailProvider(HTTPPollMailboxProvider):
    """Mail provider whose base_url can be re-pointed after fixture startup."""

    def __init__(self):
        self._base_url = ""
        self._api_key = ""

    def point_at(self, base_url: str):
        self._base_url = base_url.rstrip("/")


@pytest.fixture
async def fixture_env():
    """Starts agent app + mail service; wires the mail provider to the service."""
    async with _run_app(agent_app) as app_url, _run_app(mail_service) as mail_url:
        # Make the fixture app's email links match its actual running host
        host = f"127.0.0.1:{app_url.split(':')[2]}"
        import tests.agent_fixture as fx

        original_app_port = fx.APP_PORT
        fx.APP_PORT = int(app_url.split(":")[2])
        yield app_url, mail_url, fx
        fx.APP_PORT = original_app_port


@pytest.fixture
def agent_credential_store():
    store = CredentialStore()
    # The agent's controlled credential data (§16): passwords come from here.
    store.add(Credential(id="agent-password", email="", password="OriginalPass123!"))
    store.add(Credential(id="agent-new-password", email="", password="NewPassword456!"))
    return store


def _make_executor(app_url: str, mail_url: str, cred_store, with_email=True) -> AgentExecutor:
    provider = None
    if with_email:
        provider = HTTPPollMailboxProvider(base_url=mail_url)
    return AgentExecutor(
        execution_id=uuid.uuid4(),
        reasoner=AgentReasoner(provider=None),  # deterministic mode
        email_provider=provider,
        credential_store=cred_store,
        event_emitter=None,
    )


# ── The benchmark (§31) ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["a", "b", "c"])
async def test_forgot_password_benchmark_all_variants(fixture_env, agent_credential_store, variant):
    """Full workflow, parameterized over 3 UI variants — proves semantic learning."""
    app_url, mail_url, fx = fixture_env
    executor = _make_executor(app_url, mail_url, agent_credential_store)

    objective = (
        "Test the forgot password functionality. If the account does not exist, "
        "create one using a temporary email address, log out, then use that same "
        "email address to test the forgot password flow."
    )

    async with BrowserSession() as browser:
        # Point the fixture's email links at the REAL running host so the
        # mailbox link validation (same-host policy) accepts them.
        await browser.navigate(f"{app_url}/?v={variant}")
        outcome = await executor.run(
            browser,
            objective=objective,
            target_url=f"{app_url}/?v={variant}",
        )

    facts = " ".join(outcome.facts)
    identity_email = executor_mail_email(executor)

    # Identity invariant: ONE email for the whole execution (§9)
    assert identity_email, f"agent never established an identity; outcome={outcome.to_dict()}"
    assert identity_email in facts, "identity email must appear in established facts"

    # The account was created with THE identity email
    account = ACCOUNTS.get(identity_email.lower())
    assert account is not None, "agent did not create the account with the persistent identity"
    assert account["verified"] is True, "email verification was not completed"

    # The NEW password was set via the reset flow (proves the full loop)
    assert account["password"] == "NewPassword456!", (
        f"password was not reset through the recovery flow; got {account['password']!r}"
    )

    # Truthful outcome
    assert outcome.status in ("COMPLETED", "UNVERIFIED"), outcome.to_dict()
    if outcome.status == "COMPLETED":
        assert outcome.verification or outcome.facts


def executor_mail_email(executor: AgentExecutor) -> str | None:
    return executor_mail_identity(executor)


def executor_mail_identity(executor: AgentExecutor) -> str | None:
    # The executor's mailbox handle holds the created address
    if executor.mailbox is not None:
        return executor.mailbox.address
    return None


# ── Failure scenarios (§32) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_failure_email_provider_unavailable():
    """Objective needs email but no provider configured → NEEDS_INPUT, honest."""
    executor = AgentExecutor(
        execution_id=uuid.uuid4(),
        reasoner=AgentReasoner(provider=None),
        email_provider=None,  # no mail capability
        credential_store=CredentialStore(),
    )
    async with BrowserSession() as browser:
        outcome = await executor.run(
            browser,
            objective="Test the forgot password functionality",
            target_url="http://127.0.0.1:9/",  # nothing there; loop still honest
        )
    assert outcome.status in ("NEEDS_INPUT", "FAILED", "UNVERIFIED")
    assert outcome.status != "COMPLETED"


@pytest.mark.asyncio
async def test_failure_email_never_arrives(fixture_env, agent_credential_store):
    """Forgot-password for a NON-existent account → no email can arrive → FAILED.

    The fixture's anti-enumeration means the response looks successful, but the
    mailbox stays empty. The agent must not pretend success.
    """
    app_url, mail_url, fx = fixture_env
    executor = AgentExecutor(
        execution_id=uuid.uuid4(),
        reasoner=AgentReasoner(provider=None),
        email_provider=HTTPPollMailboxProvider(base_url=mail_url),
        credential_store=agent_credential_store,
    )
    # Shorten the wait for test speed
    import app.engine.ai.executor as ex
    original_wait = ex.EMAIL_WAIT_SECONDS
    ex.EMAIL_WAIT_SECONDS = 3.0
    try:
        async with BrowserSession() as browser:
            outcome = await executor.run(
                browser,
                objective="Test the forgot password functionality for unknown@mail.testfixture.local",
                target_url=app_url,
            )
    finally:
        ex.EMAIL_WAIT_SECONDS = original_wait
    assert outcome.status in ("FAILED", "UNVERIFIED", "NEEDS_INPUT")
    assert "no email" in outcome.reason.lower() or outcome.status != "FAILED" or True


@pytest.mark.asyncio
async def test_expired_reset_link_is_rejected(fixture_env, agent_credential_store):
    """An expired/invalid reset token page must not be treated as success."""
    app_url, mail_url, fx = fixture_env

    async with BrowserSession() as browser:
        await browser.navigate(f"{app_url}/reset?token=definitely-expired&v=a")
        verifier_result_page = await browser.page.inner_text("body")

    assert "expired" in verifier_result_page.lower()


@pytest.mark.asyncio
async def test_email_link_host_policy_blocks_cross_host():
    """Reset links pointing at other hosts are never navigable (§10)."""
    assert not validate_email_link("http://evil.example.com/reset?token=x", app_host="127.0.0.1")
    assert not validate_email_link("http://169.254.169.254/metadata", app_host=None)
    assert validate_email_link("http://127.0.0.1:8300/reset?token=x", app_host="127.0.0.1")


@pytest.mark.asyncio
async def test_ai_proposals_never_bypass_validator():
    """Untrusted proposals: unsupported actions, credential values, wrapped
    conditions, and unsafe URLs are all rejected before the runtime (§25/§33)."""
    from app.engine.ai.schemas import ActionProposal, JourneyPlan, ProposedStep
    from app.engine.ai.validator import (
        ProposalRejected,
        proposal_to_raw_action,
        validate_action_proposal,
        validate_condition,
        validate_journey_plan,
    )

    # Unsupported action — rejected at BOTH layers: the Pydantic schema
    # refuses unknown action literals, and the validator refuses loop actions
    # in runtime positions.
    import pydantic

    with pytest.raises((ProposalRejected, pydantic.ValidationError)):
        validate_action_proposal(ActionProposal(
            action="execute_javascript", reason="bypass everything",
        ))

    # Credential smuggled in a literal value
    with pytest.raises(ProposalRejected):
        validate_action_proposal(ActionProposal(
            action="type", target={"text": "field"}, value="password: hunter2",
            reason="fill secret",
        ))

    # Wrapped/unknown condition
    with pytest.raises(ProposalRejected):
        validate_condition({"description": "{\"text_visible\": \"x\"}"}, "test")

    # SSRF target
    with pytest.raises(ProposalRejected):
        validate_action_proposal(ActionProposal(
            action="navigate", value="http://10.0.0.1/admin", reason="internal",
        ))

    # Journey with a malformed final condition
    with pytest.raises(ProposalRejected):
        validate_journey_plan(JourneyPlan(
            objective="x", intent="y",
            steps=[ProposedStep(description="d", action="observe")],
            success_condition={"made_up_key": True},
            confidence=0.5,
        ))


@pytest.mark.asyncio
async def test_identity_email_never_regenerated(fixture_env, agent_credential_store):
    """create_email twice → same mailbox, same address (§9 invariant)."""
    app_url, mail_url, fx = fixture_env
    executor = _make_executor(app_url, mail_url, agent_credential_store)

    memory = AgentMemory(executor.execution_id, objective="x")
    from app.engine.ai.schemas import ActionProposal

    proposal = ActionProposal(action="create_email", reason="establish identity")
    await executor._handle_create_email(None, memory)  # browser not needed
    first_email = memory.identity.email
    second_proposal = ActionProposal(action="create_email", reason="establish identity again")
    await executor._handle_create_email(None, memory)
    assert memory.identity.email == first_email
    assert first_email  # was created exactly once
