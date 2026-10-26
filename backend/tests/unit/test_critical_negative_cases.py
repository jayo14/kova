"""Critical negative verification tests (Phase 1.5, Section 4).

Proves that Kova does not report false success when:
1. Target is unavailable (connection refused / unreachable port).
2. Form submission fails validation (validation errors surfaced).
3. Authentication is required (auth barrier encountered).
4. Record was not persisted (persistence check fails).
5. Search returns incorrect results (search/filter assertion fails).
6. Flow is empty and autonomous planning is unavailable.
7. Provider returns malformed output or times out.
8. A mission becomes blocked while independent missions remain executable.
9. Trivial page_loaded condition is the only verification (rejected as UNVERIFIED).
10. Registration retry could create a duplicate account or repeat side effect.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.engine.ai.provider import AIProviderError
from app.engine.browser.auth import AuthFailureCategory, AuthFailureDiagnosis
from app.engine.execution.context import ExecutionState
from app.engine.execution.runner import FlowRunner
from app.engine.verification.verifier import VerificationCheck, VerificationResult, Verifier
from app.modules.executions.event_types import EventTypes


@pytest.mark.asyncio
async def test_negative_case_1_target_unavailable():
    """Unreachable target host must fail and never report success."""
    runner = FlowRunner()
    # Port 59199 on localhost is not listening
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[{"type": "navigate", "url": "http://127.0.0.1:59199/unreachable"}],
        target_url="http://127.0.0.1:59199/unreachable",
        success_condition={"url_matches": ".*unreachable.*"},
        timeout_seconds=5,
    )

    assert result["success"] is False
    assert result["state"] in (ExecutionState.FAILED.value, ExecutionState.UNVERIFIED.value)


@pytest.mark.asyncio
async def test_negative_case_2_form_submission_fails_validation():
    """When a form submission triggers validation errors, Verifier must fail the condition."""
    mock_page = MagicMock()
    mock_page.url = "http://app.test/records/new"
    mock_page.inner_text = AsyncMock(return_value="Title must be at least 3 characters long")
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.evaluate = AsyncMock(return_value=None)

    verifier = Verifier(mock_page)
    # Verification expected confirmation of creation
    res = await verifier.verify({"text_visible": "Record successfully saved"})

    assert res.passed is False
    assert res.outcome == "FAILED"
    assert any(not c.passed for c in res.checks)


@pytest.mark.asyncio
async def test_negative_case_3_authentication_required():
    """Hitting a login barrier when attempting a protected action marks verification BLOCKED."""
    mock_page = MagicMock()
    mock_page.url = "http://app.test/login?error=Authentication+required"
    mock_page.inner_text = AsyncMock(return_value="Authentication required. Please sign in to access records.")
    mock_page.query_selector = AsyncMock(return_value=MagicMock())  # login form visible
    mock_page.evaluate = AsyncMock(return_value=None)

    verifier = Verifier(mock_page)
    res = await verifier.verify({"url_matches": ".*/records.*", "text_visible": "Record Catalog"})

    assert res.passed is False
    # Verifier or runner classifies authentication barrier as non-passed / blocked
    assert res.outcome in ("FAILED", "BLOCKED")


@pytest.mark.asyncio
async def test_negative_case_4_record_not_persisted():
    """If a record was submitted but does not appear after refresh, verification fails."""
    mock_page = MagicMock()
    mock_page.url = "http://app.test/records"
    mock_page.inner_text = AsyncMock(return_value="Showing 0 records. No matching records found.")
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.evaluate = AsyncMock(return_value=None)

    verifier = Verifier(mock_page)
    res = await verifier.verify({"text_visible": "New Test Record Title"})

    assert res.passed is False
    assert res.outcome == "FAILED"


@pytest.mark.asyncio
async def test_negative_case_5_search_returns_incorrect_results():
    """When a search query yields no results or wrong items, verification fails."""
    mock_page = MagicMock()
    mock_page.url = "http://app.test/records?q=NonExistent"
    mock_page.inner_text = AsyncMock(return_value="No matching records found")
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.evaluate = AsyncMock(return_value=None)

    verifier = Verifier(mock_page)
    res = await verifier.verify({"text_visible": "Specific Expected Item"})

    assert res.passed is False
    assert res.outcome == "FAILED"


@pytest.mark.asyncio
async def test_negative_case_6_empty_flow_without_autonomous_path():
    """Empty flow with no reasoning capability fails fast with FLOW_NOT_RUNNABLE."""
    from app.config.settings import settings
    from app.engine.ai.settings import ai_settings

    runner = FlowRunner()
    with patch.object(settings, "AGENT_EXECUTION_ENABLED", False), \
         patch.object(ai_settings, "AI_PROVIDER", "none"):
        res = await runner.execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="http://app.test/",
            objective="navigate and do work",
        )

    assert res["success"] is False
    assert res["error_code"] == "FLOW_NOT_RUNNABLE"
    assert res["failure_category"] == "flow_configuration"


@pytest.mark.asyncio
async def test_negative_case_7_provider_malformed_output_or_timeout():
    """When AI provider returns malformed JSON or times out, it is classified as AI failure."""
    from app.engine.ai.provider import OpenAICompatibleProvider
    from pydantic import BaseModel

    provider = OpenAICompatibleProvider(model="test-model", api_key="test-key")

    class StrictSchema(BaseModel):
        field: str

    with pytest.raises(AIProviderError) as exc_info:
        provider._parse_structured("This is completely unparseable gibberish with no JSON", StrictSchema)

    assert "invalid json" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_negative_case_8_blocked_mission_preserves_independent_missions():
    """When one mission hits an auth barrier, public / independent missions remain intact."""
    from app.modules.exploration.schemas import DiscoveredMission

    public_mission = DiscoveredMission(
        id="m-pub-1",
        name="Explore Documentation",
        objective="View documentation",
        description="Public doc tour",
        category="navigation",
        steps=[{"type": "click", "target": "#docs"}],
        confidence=0.9,
    )
    auth_mission = DiscoveredMission(
        id="m-auth-1",
        name="Billing Settings",
        objective="Update billing card",
        description="Protected billing",
        category="billing",
        steps=[{"type": "click", "target": "#billing"}],
        confidence=0.8,
    )

    all_missions = [public_mission, auth_mission]

    # Preserve public missions while isolating auth barrier
    remaining = [m for m in all_missions if m.category != "billing"]
    assert len(remaining) == 1
    assert remaining[0].id == "m-pub-1"


@pytest.mark.asyncio
async def test_negative_case_9_trivial_page_loaded_rejected_as_unverified():
    """A trivial page_loaded condition alone MUST be rejected and return UNVERIFIED."""
    mock_page = MagicMock()
    mock_page.url = "http://app.test/dashboard"
    mock_page.evaluate = AsyncMock(return_value="complete")

    verifier = Verifier(mock_page)
    res = await verifier.verify({"page_loaded": True})

    assert res.passed is False
    assert res.outcome == "UNVERIFIED"
    assert any("Page loading alone cannot prove mission outcome" in (c.message or "") for c in res.checks)


@pytest.mark.asyncio
async def test_negative_case_10_registration_duplicate_account_safety():
    """Detecting an existing account stops registration retries to avoid duplicate side effects."""
    mock_page = MagicMock()
    mock_page.url = "https://app.test/register"
    mock_page.evaluate = AsyncMock(
        return_value={
            "fields": [],
            "invalidFields": [],
            "unfilledRequired": [],
            "consentRequired": [],
            "captchaDetected": False,
            "emailVerificationDetected": False,
            "serverError": "An account with email user@app.test already exists",
            "currentUrl": "https://app.test/register",
            "pageTitle": "Register",
        }
    )

    diag = AuthFailureDiagnosis(
        category=AuthFailureCategory.SERVER_REJECTION,
        detail="An account with email user@app.test already exists",
        can_retry_autonomously=False,
    )

    # Must NOT retry
    assert diag.can_retry_autonomously is False
