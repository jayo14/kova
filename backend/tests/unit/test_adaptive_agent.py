import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.engine.browser.auth import (
    AuthFailureCategory,
    diagnose_auth_failure,
    attempt_registration_recovery,
)
from app.engine.exploration.explorer import ExplorationEngine
from app.engine.verification.verifier import Verifier, VerificationCheck, VerificationResult
from app.modules.exploration.models import ExplorationStatus


@pytest.mark.asyncio
async def test_diagnose_auth_failure_missing_fields():
    """Verify diagnose_auth_failure identifies missing required fields and consent checkboxes."""
    mock_page = MagicMock()
    mock_page.url = "https://getpresently.com.ng/register"

    # Mock evaluate returning fields, unfilled required fields, and unchecked terms
    eval_return = {
        "url": "https://getpresently.com.ng/register",
        "title": "Create Account - Presently",
        "hasAlert": False,
        "alertText": "",
        "unfilledRequired": ["confirm_password", "terms"],
        "fields": [
            {"name": "email", "type": "email", "required": True, "value": "test@example.com"},
            {"name": "password", "type": "password", "required": True, "value": "Secret123!"},
            {"name": "confirm_password", "type": "password", "required": True, "value": ""},
            {"name": "terms", "type": "checkbox", "required": True, "checked": False},
        ],
        "hasCaptcha": False,
        "isAuthPage": True,
        "statusCodes": [],
        "bodyText": "Register for presently",
    }
    mock_page.evaluate = AsyncMock(return_value=eval_return)

    cred = {"email": "test@example.com", "password": "Secret123!"}
    diag = await diagnose_auth_failure(mock_page, is_signup=True, initial_url="https://getpresently.com.ng/register", credential=cred)

    assert diag.category in (
        AuthFailureCategory.CUSTOM_FIELDS_REQUIRED,
        AuthFailureCategory.CLIENT_VALIDATION,
        AuthFailureCategory.REQUIRED_CONSENT,
    )
    assert diag.can_retry_autonomously is True
    assert "confirm_password" in diag.missing_fields or "terms" in diag.missing_fields


@pytest.mark.asyncio
async def test_registration_recovery_auto_fills_and_checks_terms():
    """Verify attempt_registration_recovery fills confirmation password, accepts terms, and clicks submit."""
    mock_page = MagicMock()
    mock_page.url = "https://getpresently.com.ng/register"

    mock_checkbox = MagicMock()
    mock_checkbox.is_visible = AsyncMock(return_value=True)
    mock_checkbox.is_checked = AsyncMock(return_value=False)
    mock_checkbox.check = AsyncMock()

    mock_confirm_input = MagicMock()
    mock_confirm_input.is_visible = AsyncMock(return_value=True)
    mock_confirm_input.fill = AsyncMock()

    mock_submit_btn = MagicMock()
    mock_submit_btn.is_visible = AsyncMock(return_value=True)

    async def on_submit(*args, **kwargs):
        mock_page.url = "https://getpresently.com.ng/dashboard"

    mock_submit_btn.click = AsyncMock(side_effect=on_submit)

    def mock_locator(selector):
        loc = MagicMock()
        if "checkbox" in selector or "terms" in selector or "agree" in selector:
            loc.all = AsyncMock(return_value=[mock_checkbox])
            loc.count = AsyncMock(return_value=1)
            loc.first = mock_checkbox
        elif "confirm" in selector:
            loc.all = AsyncMock(return_value=[mock_confirm_input])
            loc.count = AsyncMock(return_value=1)
            loc.first = mock_confirm_input
        elif "submit" in selector or "button" in selector:
            loc.all = AsyncMock(return_value=[mock_submit_btn])
            loc.count = AsyncMock(return_value=1)
            loc.first = mock_submit_btn
        else:
            loc.all = AsyncMock(return_value=[])
            loc.count = AsyncMock(return_value=0)
            loc.first = MagicMock(is_visible=AsyncMock(return_value=False))
        return loc

    mock_page.locator = MagicMock(side_effect=mock_locator)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    from app.engine.browser.auth import AuthFailureDiagnosis

    diag = AuthFailureDiagnosis(
        category=AuthFailureCategory.CUSTOM_FIELDS_REQUIRED,
        detail="Missing required inputs: confirm_password, terms",
        missing_fields=["confirm_password", "terms"],
        consent_required=["Terms and Conditions"],
        unfilled_required_fields=[
            {"name": "confirm_password", "label": "Confirm Password", "type": "password"}
        ],
        can_retry_autonomously=True,
    )

    cred = {"email": "test@example.com", "password": "Secret123!"}
    with patch("app.engine.browser.auth.find_submit_button", AsyncMock(return_value=mock_submit_btn)):
        recovered, detail = await attempt_registration_recovery(mock_page, diag, cred)

    assert recovered is True
    assert "navigated to" in detail.lower()
    mock_confirm_input.fill.assert_awaited()
    mock_checkbox.check.assert_awaited()
    mock_submit_btn.click.assert_awaited()


@pytest.mark.asyncio
async def test_exploration_preserves_discoveries_and_public_missions_on_auth_barrier():
    """Verify exploration retains findings, goal, and public missions when an auth barrier is hit."""
    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://getpresently.com.ng/",
        goal=None,
        event_emitter=AsyncMock(),
    )

    mock_page = MagicMock()
    mock_page.url = "https://getpresently.com.ng/register"
    mock_page.title = AsyncMock(return_value="Presently - Gift with Meaning")
    mock_page.set_default_navigation_timeout = MagicMock()
    mock_page.set_default_timeout = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.eval_on_selector_all = AsyncMock(return_value=["Explore Gifts", "About Us"])

    class MockContextManager:
        async def __aenter__(self):
            return mock_page
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_browser = MagicMock()
    mock_browser.is_started = True
    mock_browser.page = mock_page
    mock_browser.browser_context = MagicMock(return_value=MockContextManager())
    mock_browser.start = AsyncMock(return_value=mock_page)
    mock_browser.observe = AsyncMock(return_value={
        "url": "https://getpresently.com.ng/register",
        "title": "Presently - Gift with Meaning",
        "elements": [
            {"type": "link", "name": "Explore Gifts"},
            {"type": "link", "name": "About Us"},
            {"type": "button", "name": "Create Account"},
        ],
        "text": "Send and receive meaningful gifts with friends.",
    })
    mock_browser.close = AsyncMock()
    engine._browser = mock_browser

    # Seed discovered sections and inferred goal
    engine._discovered_sections = [
        {"tag": "nav", "label": "Navigation Header", "interactiveCount": 3},
        {"tag": "section", "label": "Gift Collection", "interactiveCount": 6},
    ]
    engine.goal = "Verify core journeys for: Send and receive meaningful gifts"

    # Simulate hitting auth barrier with no credential
    from app.engine.ai.schemas import AuthPageClassification
    auth_signup = AuthPageClassification(
        kind="signup",
        confidence=1.0,
        reasoning="Registration page detected on target site",
    )

    sample_routes = [
        {
            "path": "/explore",
            "url": "https://getpresently.com.ng/explore",
            "text": "Explore Gifts",
            "accessible": True,
            "status": 200,
            "role": "Visitor",
            "category": "navigation",
            "is_button": False,
            "elements_count": 5,
        },
        {
            "path": "/about",
            "url": "https://getpresently.com.ng/about",
            "text": "About Us",
            "accessible": True,
            "status": 200,
            "role": "Visitor",
            "category": "navigation",
            "is_button": False,
            "elements_count": 3,
        },
    ]

    with patch("app.engine.browser.auth.observe_auth_signals", AsyncMock()), \
         patch("app.engine.browser.auth.classify_auth_page", return_value=auth_signup), \
         patch.object(engine, "_detect_authentication", AsyncMock(return_value=True)), \
         patch.object(engine, "_validate_page", AsyncMock()), \
         patch.object(engine, "_capture_and_emit_screenshot", AsyncMock()), \
         patch.object(engine, "_extract_brand_metadata", AsyncMock(return_value={"brand_name": "Presently"})), \
         patch.object(engine, "_analyze_routes", AsyncMock(return_value=sample_routes)), \
         patch.object(engine, "_stream_page_exploration", AsyncMock()):
        result = await engine.explore(credential=None, selected_role=None)

        # Must not wipe discoveries or missions!
        assert len(result["discoveries"]) > 0
        assert len(result["candidate_missions"]) > 0
        assert result["goal"] is not None
        assert result["selected_role"] is not None
        # Public journeys exist, so status is READY
        assert result["status"] == ExplorationStatus.READY
        assert result["credential_request"] is not None


@pytest.mark.asyncio
async def test_verifier_outcome_categorization():
    """Verify Verifier categorizes PASSED, FAILED, UNVERIFIED, and BLOCKED outcomes."""
    mock_page = MagicMock()
    mock_page.url = "https://example.com/dashboard"

    verifier = Verifier(mock_page)

    # 1. Vacuous page_loaded only condition must yield UNVERIFIED
    res_vacuous = await verifier.verify({"page_loaded": True})
    assert res_vacuous.passed is False
    assert res_vacuous.outcome == "UNVERIFIED"

    # 2. Unknown keys must yield UNVERIFIED
    res_unknown = await verifier.verify({"invalid_check_key": "some_value"})
    assert res_unknown.passed is False
    assert res_unknown.outcome == "UNVERIFIED"

    # 3. Text visible that matches yields PASSED
    mock_page.evaluate = AsyncMock(return_value="Welcome to your Dashboard!")
    with patch.object(verifier, "_check_text_visible", AsyncMock(return_value=VerificationCheck(type="text_visible", passed=True))):
        res_pass = await verifier.verify({"text_visible": "Welcome"})
        assert res_pass.passed is True
        assert res_pass.outcome == "PASSED"

    # 4. Auth barrier yields BLOCKED
    blocked_check = VerificationCheck(
        type="auth_barrier",
        passed=False,
        message="Authentication barrier encountered — login required",
    )
    res_blocked = VerificationResult(passed=False, checks=[blocked_check])
    assert res_blocked.outcome == "BLOCKED"
