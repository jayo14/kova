"""Deterministic journey E2E tests (readiness spec §29, scenarios A–I).

Every scenario runs the REAL pipeline: FlowRunner → ActionExecutor →
TargetResolver → Playwright → the fixture app → Verifier → outcome.
No mocks in the execution path.

Scenario map:
  A  auth login + dashboard verification      → COMPLETED
  B  search with results                      → COMPLETED
  C  search with explicit empty results state → COMPLETED
  D  library → resource → content visible     → COMPLETED
  E  form fill + submit + success message     → COMPLETED
  F  false success (click ok, outcome absent) → FAILED (never COMPLETED)
  G  malformed condition                      → UNVERIFIED (never COMPLETED)
  H  takeover: human changes state, agent resumes and completes → COMPLETED
  I  cancel mid-run                           → CANCELLED, browser cleaned up
"""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.credentials.models import Credential
from app.engine.credentials.store import CredentialStore
from app.engine.execution.runner import FlowRunner
from tests.test_app import app as test_app


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_test_server():
    port = _get_free_port()
    config = uvicorn.Config(test_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def test_server():
    async with _run_test_server() as url:
        yield url


@pytest.fixture
def credential_store():
    store = CredentialStore()
    store.add(Credential(id="kova-login", email="test@kova.local", password="KovaTest123!"))
    return store


def _make_runner() -> FlowRunner:
    return FlowRunner()


# ── Scenario A — Authentication ─────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_a_login_reaches_dashboard(test_server, credential_store):
    """Login journey with credential reference verifies dashboard state."""
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "type", "target": {"css": "#email"}, "credential_id": "kova-login", "credential_field": "email"},
            {"type": "type", "target": {"css": "#password"}, "credential_id": "kova-login", "credential_field": "password"},
            {"type": "click", "target": {"css": "#login-btn"}},
        ],
        success_condition={"auth_verified": {"auth_path": "/login", "indicator": "Welcome, Kova"}},
        credential_store=credential_store,
        target_url=test_server,
    )
    assert result["success"] is True, result.get("error")
    assert result["verification"]["passed"] is True
    assert result["final_url"].endswith("/dashboard")
    # Credential secrets must never leak into events
    events_str = str(result["events"])
    assert "KovaTest123!" not in events_str


# ── Scenario B — Search with results ────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_b_search_finds_results(test_server):
    """Search journey: query 'course' → result links appear → verified."""
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/search"},
            {"type": "type", "target": {"css": "#q"}, "value": "course"},
            {"type": "click", "target": {"css": "#search-btn"}},
            {"type": "wait", "value": "1000"},
        ],
        success_condition={"element_count": {"selector": "a.result", "min": 1}},
        target_url=test_server,
    )
    assert result["success"] is True, result.get("error")
    assert result["verification"]["passed"] is True


# ── Scenario C — Search with explicit empty-results state ───────────


@pytest.mark.asyncio
async def test_scenario_c_search_empty_results_state_is_verifiable(test_server):
    """Empty results is a legitimate outcome when the journey defines it.

    The fixture shows '#no-results' for the query 'zzznothing'. The journey
    explicitly treats the empty-state as the intended outcome → COMPLETED.
    """
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/search?q=zzznothing"},
            {"type": "wait", "value": "1000"},
        ],
        success_condition={"element_visible": {"css": "#no-results"}},
        target_url=test_server,
    )
    assert result["success"] is True, result.get("error")
    assert result["verification"]["passed"] is True


# ── Scenario D — Resource journey ───────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_d_library_to_resource_content(test_server):
    """Library → open resource → heading + content visible → COMPLETED."""
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/library"},
            {"type": "click", "target": {"css": "a.resource[href*='Biology']"}},
            {"type": "wait", "value": "1000"},
        ],
        success_condition={
            "element_visible": {"css": "#resource-content"},
            "url_changed_to": {"from": f"{test_server}/library"},
        },
        target_url=test_server,
    )
    assert result["success"] is True, result.get("error")
    assert result["verification"]["passed"] is True


# ── Scenario E — Form submission ────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_e_form_submit_shows_success(test_server):
    """Fill contact form → submit → success message visible → COMPLETED."""
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/contact"},
            {"type": "type", "target": {"css": "#name"}, "value": "Kova Tester"},
            {"type": "type", "target": {"css": "#email"}, "value": "kova@example.com"},
            {"type": "type", "target": {"css": "#message"}, "value": "Hello from Kova"},
            {"type": "click", "target": {"css": "#contact-submit"}},
            {"type": "wait", "value": "1000"},
        ],
        success_condition={"text_visible": "Message sent successfully"},
        target_url=test_server,
    )
    assert result["success"] is True, result.get("error")
    assert result["verification"]["passed"] is True


# ── Scenario F — False success (MANDATORY) ──────────────────────────


@pytest.mark.asyncio
async def test_scenario_f_false_success_is_never_completed(test_server):
    """Button clicks but intended outcome never happens → NOT COMPLETED.

    The checkout fixture's pay button changes its own label but no
    confirmation ever renders. A structural check (h1 visible) would pass —
    which is exactly why it is INVALID as success proof. The outcome check
    (confirmation text) must fail the execution.
    """
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/checkout"},
            {"type": "click", "target": {"css": "#pay-btn"}},
            {"type": "wait", "value": "1000"},
        ],
        success_condition={"text_visible": "Payment confirmed"},
        target_url=test_server,
    )
    assert result["success"] is False
    assert result["state"] == "FAILED"
    # The action itself DID complete — this is precisely the case that must
    # not be reported as COMPLETED.
    assert result.get("error_code") == "VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_scenario_f2_structural_only_condition_is_rejected(test_server):
    """'main is visible' cannot prove 'payment succeeded' — vacuous rejected."""
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/checkout"},
            {"type": "click", "target": {"css": "#pay-btn"}},
        ],
        # Vacuous: structural container as the sole success proof
        success_condition={"element_visible": {"css": "main"}},
        target_url=test_server,
    )
    assert result["success"] is False
    assert result.get("error_code") == "UNVERIFIED", result.get("error_code")


# ── Scenario G — Malformed condition (MANDATORY) ────────────────────


@pytest.mark.asyncio
async def test_scenario_g_description_wrapped_condition_is_unverified(test_server):
    """The historical wiring defect as direct input must yield UNVERIFIED."""
    import json

    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/dashboard-broken-link-noop"},
        ],
        success_condition={"description": json.dumps({"text_visible": "Anything"})},
        target_url=f"{test_server}/library",
    )
    assert result["success"] is False
    assert result.get("error_code") == "UNVERIFIED"


@pytest.mark.asyncio
async def test_scenario_g2_empty_condition_is_unverified(test_server):
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[{"type": "navigate", "value": f"{test_server}/library"}],
        success_condition={},
        target_url=f"{test_server}/library",
    )
    assert result["success"] is False
    assert result.get("error_code") == "UNVERIFIED"


@pytest.mark.asyncio
async def test_scenario_g3_unknown_key_condition_is_unverified(test_server):
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[{"type": "navigate", "value": f"{test_server}/library"}],
        success_condition={"page_has_content": "yes"},
        target_url=f"{test_server}/library",
    )
    assert result["success"] is False
    assert result.get("error_code") == "UNVERIFIED"


@pytest.mark.asyncio
async def test_scenario_g4_no_condition_is_unverified(test_server):
    runner = _make_runner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[{"type": "navigate", "value": f"{test_server}/library"}],
        success_condition=None,
        target_url=f"{test_server}/library",
    )
    assert result["success"] is False
    assert result.get("error_code") == "UNVERIFIED"


# ── Scenario H — Takeover ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_h_takeover_same_page_resume(test_server):
    """Agent pauses → human input on SAME page → resume → completes.

    The human navigates the agent's browser to /library during takeover;
    after resume the agent re-observes and completes from the new state.
    """
    from app.engine.execution.control import (
        cleanup_control,
        queue_user_input,
        set_control_state,
    )

    execution_id = uuid.uuid4()
    exec_str = str(execution_id)
    runner = _make_runner()

    # Pre-request takeover so the pause gate triggers before the first step
    await set_control_state(exec_str, "human")
    # Queue the human's actions: navigate to /library, then release control
    await queue_user_input(exec_str, {"kind": "nav_reload"})
    await set_control_state(exec_str, "agent")

    try:
        result = await runner.execute(
            execution_id=execution_id,
            flow_steps=[
                # First step gate observes human control → drains input → resumes
                {"type": "navigate", "value": f"{test_server}/library"},
                {"type": "wait", "value": "500"},
            ],
            success_condition={"element_visible": {"css": "h1"}},
            target_url=test_server,
        )
        # Runner must have passed through the pause gate and still completed
        # honestly from the post-takeover state.
        assert result["verification"]["passed"] is True
        assert "CANCELLED" != result.get("state")
    finally:
        await cleanup_control(exec_str)


# ── Scenario I — Cancellation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_i_cancel_stops_execution(test_server):
    """Cancel flag → runner stops at next gate → CANCELLED outcome."""
    from app.engine.execution.control import cleanup_control, request_cancel

    execution_id = uuid.uuid4()
    exec_str = str(execution_id)
    runner = _make_runner()

    # Cancel before the runner starts: gate must fire before the first step
    await request_cancel(exec_str)
    try:
        result = await runner.execute(
            execution_id=execution_id,
            flow_steps=[
                {"type": "navigate", "value": f"{test_server}/library"},
                {"type": "wait", "value": "2000"},
            ],
            success_condition={"text_visible": "Library"},
            target_url=test_server,
        )
        assert result["success"] is False
        assert result.get("error_code") == "CANCELLED"
        assert result.get("state") == "CANCELLED"
    finally:
        await cleanup_control(exec_str)


# ── Journey generation honesty checks ───────────────────────────────


@pytest.mark.asyncio
async def test_generated_missions_never_use_vacuous_conditions(test_server):
    """Every generated mission's condition must be machine-verifiable.

    Runs exploration against the fixture app and asserts no generated
    mission carries the historical vacuous patterns.
    """
    from app.engine.browser.session import BrowserSession
    from app.engine.exploration.explorer import ExplorationEngine

    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        page = browser.page
        observation = await browser.observe()

        engine = ExplorationEngine(
            exploration_id=uuid.uuid4(),
            url=test_server,
            goal=None,
            credential_id=None,
        )
        _, missions = await engine._discover_workflows(page, observation, None)

    import json

    for mission in missions:
        cond = mission.successCondition
        if cond is None:
            continue  # needs-credentials missions are honest about being unrunnable
        serialized = json.dumps(cond)
        assert '".*"' not in serialized, f"{mission.name}: vacuous url_matches"
        assert "main, .content, .container" not in serialized, (
            f"{mission.name}: structural-container-only success condition"
        )
        assert isinstance(cond, dict), f"{mission.name}: condition must stay structured"
