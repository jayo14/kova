import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engine.verification.verifier import Verifier, KNOWN_CONDITION_KEYS, is_vacuous_condition


@pytest.mark.asyncio
async def test_record_persisted_matching():
    mock_page = AsyncMock()
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Record Details: rec-42 Title: Alpha Feature Priority: High"
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({
        "record_persisted": {
            "expected_fields": {"Title": "Alpha Feature", "Priority": "High"},
            "reload": False,
        }
    })

    assert res.passed is True
    assert res.outcome == "PASSED"
    assert len(res.checks) == 1
    check = res.checks[0]
    assert check.type == "record_persisted"
    assert check.passed is True
    assert check.details["verified_fields"] == {"Title": "Alpha Feature", "Priority": "High"}


@pytest.mark.asyncio
async def test_record_persisted_missing_field_fails():
    mock_page = AsyncMock()
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Record Details: rec-42 Title: Alpha Feature"
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({
        "record_persisted": {
            "expected_fields": {"Title": "Alpha Feature", "Priority": "Critical"},
            "reload": False,
        }
    })

    assert res.passed is False
    assert res.outcome == "FAILED"
    check = res.checks[0]
    assert check.passed is False
    assert "Priority='Critical'" in check.message


@pytest.mark.asyncio
async def test_record_persisted_with_reload():
    mock_page = AsyncMock()
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "System Baseline infrastructure high owner: testuser"
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({
        "record_persisted": {
            "expected_text": ["System Baseline", "infrastructure"],
            "reload": True,
        }
    })

    assert res.passed is True
    mock_page.reload.assert_awaited_once()
    assert res.checks[0].details["reloaded"] is True


@pytest.mark.asyncio
async def test_search_results_positive_and_negative_exclusion():
    mock_page = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.count.return_value = 1
    mock_loc.first.inner_text.return_value = "rec-101 Payment Gateway Integration\nrec-102 Stripe webhook"
    mock_page.locator.return_value = mock_loc

    verifier = Verifier(mock_page)
    # Target "Payment" matches rec-101, excludes "Flaky Locator"
    res = await verifier.verify({
        "search_results": {
            "query": "Payment",
            "expected_matches": ["Payment Gateway"],
            "excluded_matches": ["Flaky Locator"],
        }
    })

    assert res.passed is True
    assert res.checks[0].passed is True
    assert "verified" in res.checks[0].message


@pytest.mark.asyncio
async def test_search_results_fails_when_excluded_item_appears():
    mock_page = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.count.return_value = 1
    mock_loc.first.inner_text.return_value = "rec-101 Payment Gateway\nrec-103 Flaky Locator Diagnostic"
    mock_page.locator.return_value = mock_loc

    verifier = Verifier(mock_page)
    res = await verifier.verify({
        "search_results": {
            "query": "Payment",
            "expected_matches": ["Payment Gateway"],
            "excluded_matches": ["Flaky Locator"],
        }
    })

    assert res.passed is False
    assert "incorrectly included excluded items" in res.checks[0].message


@pytest.mark.asyncio
async def test_validation_error_observed():
    mock_page = AsyncMock()
    mock_alert = AsyncMock()
    mock_alert.count.return_value = 1
    mock_alert.first.is_visible.return_value = True
    mock_alert.first.inner_text.return_value = "Title must be at least 3 characters long."
    mock_page.locator.return_value = mock_alert

    verifier = Verifier(mock_page)
    res = await verifier.verify({
        "validation_error": {
            "message": "at least 3 characters",
            "selector": "[role='alert']",
        }
    })

    assert res.passed is True
    assert res.outcome == "PASSED"
    assert "Validation error observed" in res.checks[0].message


@pytest.mark.asyncio
async def test_validation_error_missing_fails():
    mock_page = AsyncMock()
    mock_alert = AsyncMock()
    mock_alert.count.return_value = 0
    mock_page.locator.return_value = mock_alert
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Welcome to the dashboard!"
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({
        "validation_error": {
            "message": "at least 3 characters",
        }
    })

    assert res.passed is False
    assert res.outcome == "FAILED"
    assert "was not observed" in res.checks[0].message


@pytest.mark.asyncio
async def test_app_error_absent_clean():
    mock_page = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.count.return_value = 0
    mock_page.locator.return_value = mock_loc

    verifier = Verifier(mock_page)
    res = await verifier.verify({"app_error_absent": True})
    assert res.passed is True
    assert res.checks[0].actual == "clean"


@pytest.mark.asyncio
async def test_app_error_detected():
    mock_page = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.count.return_value = 1
    mock_loc.first.is_visible.return_value = True
    mock_loc.first.inner_text.return_value = "500 Internal Server Error"
    mock_page.locator.return_value = mock_loc

    verifier = Verifier(mock_page)
    res = await verifier.verify({"app_error_absent": True})
    assert res.passed is False
    assert "500 banner detected" in res.checks[0].message


@pytest.mark.asyncio
async def test_auth_verified_with_positive_logout_signal():
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/dashboard"

    def locator_side_effect(selector):
        loc = AsyncMock()
        if "input[type='password']" in selector:
            loc.count.return_value = 0
            loc.first.count.return_value = 0
        elif "a[href*='logout']" in selector:
            loc.count.return_value = 1
            loc.first.count.return_value = 1
            loc.first.is_visible.return_value = True
        else:
            loc.count.return_value = 0
            loc.first.count.return_value = 0
            loc.first.is_visible.return_value = False
        return loc

    mock_page.locator.side_effect = locator_side_effect
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Welcome back, testuser! Here is your dashboard."
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({"auth_verified": {"auth_path": "/login"}})

    assert res.passed is True
    assert res.outcome == "PASSED"
    # Verify positive session indicator was detected
    assert any(c.type == "auth_session_indicator" and c.passed for c in res.checks)


@pytest.mark.asyncio
async def test_auth_verified_fails_on_detected_error_message():
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/login"

    def locator_side_effect(selector):
        loc = AsyncMock()
        loc.count.return_value = 0
        return loc

    mock_page.locator.side_effect = locator_side_effect
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Invalid credentials. Please check your password."
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({"auth_verified": {"auth_path": "/login"}})

    assert res.passed is False
    assert any(c.type == "auth_error_detected" and not c.passed for c in res.checks)


@pytest.mark.asyncio
async def test_auth_verified_fails_when_login_links_still_visible():
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/home"

    def locator_side_effect(selector):
        loc = AsyncMock()
        if "login" in selector.lower() or "signin" in selector.lower():
            loc.count.return_value = 1
            loc.nth.return_value.is_visible.return_value = True
        else:
            loc.count.return_value = 0
            loc.first.is_visible.return_value = False
        return loc

    mock_page.locator.side_effect = locator_side_effect
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Public page with sign in link."
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({"auth_verified": {"auth_path": "/login"}})

    assert res.passed is False
    assert any(c.type == "auth_session_indicator" and not c.passed for c in res.checks)



@pytest.mark.asyncio
async def test_auth_verified_does_not_infer_success_without_positive_evidence():
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/dashboard"

    def locator_side_effect(selector):
        loc = AsyncMock()
        loc.count.return_value = 0
        loc.first.count.return_value = 0
        loc.first.is_visible.return_value = False
        return loc

    mock_page.locator.side_effect = locator_side_effect
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Public marketing page."
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({"auth_verified": {"auth_path": "/login"}})

    assert res.passed is False
    indicator = next(c for c in res.checks if c.type == "auth_session_indicator")
    assert indicator.passed is False
    assert indicator.actual == "no_positive_session_evidence"


@pytest.mark.asyncio
async def test_record_persisted_empty_spec_fails_closed():
    mock_page = AsyncMock()
    mock_body = AsyncMock()
    mock_body.inner_text.return_value = "Anything at all"
    mock_page.query_selector.return_value = mock_body

    verifier = Verifier(mock_page)
    res = await verifier.verify({"record_persisted": {}})

    assert res.passed is False
    assert res.outcome == "FAILED"
