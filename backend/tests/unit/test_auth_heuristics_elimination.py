import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engine.execution.runner import FlowRunner


@pytest.mark.asyncio
async def test_auth_heuristics_elimination_rejects_url_only_match():
    """Visiting a URL like /dashboard or /records without positive session controls must NOT be verified as authenticated."""
    runner = FlowRunner()
    mock_page = AsyncMock()

    def locator_side_effect(selector):
        loc = AsyncMock()
        # No positive session controls found
        loc.count.return_value = 0
        return loc

    mock_page.locator.side_effect = locator_side_effect

    # Even though URL has /dashboard and /records, lack of positive DOM signals rejects auth
    is_auth = await runner._verify_authenticated_session(mock_page, "https://example.com/dashboard")
    assert is_auth is False

    is_auth_records = await runner._verify_authenticated_session(mock_page, "https://example.com/records")
    assert is_auth_records is False


@pytest.mark.asyncio
async def test_auth_heuristics_accepts_positive_session_indicator():
    """Visiting with a confirmed logout button or greeting and no login link verifies auth."""
    runner = FlowRunner()
    mock_page = AsyncMock()

    def locator_side_effect(selector):
        loc = AsyncMock()
        if "a[href*='logout']" in selector or "#user-greeting" in selector:
            loc.count.return_value = 1
            loc.first.is_visible.return_value = True
        else:
            loc.count.return_value = 0
        return loc

    mock_page.locator.side_effect = locator_side_effect

    is_auth = await runner._verify_authenticated_session(mock_page, "https://example.com/dashboard")
    assert is_auth is True


@pytest.mark.asyncio
async def test_auth_heuristics_rejects_when_login_link_visible():
    """If login/signin buttons are still visible on page, auth is rejected."""
    runner = FlowRunner()
    mock_page = AsyncMock()

    def locator_side_effect(selector):
        loc = AsyncMock()
        if "a[href*='logout']" in selector:
            loc.count.return_value = 1
            loc.first.is_visible.return_value = True
        elif "login" in selector.lower():
            loc.count.return_value = 1
            loc.nth.return_value.is_visible.return_value = True
        else:
            loc.count.return_value = 0
        return loc

    mock_page.locator.side_effect = locator_side_effect

    is_auth = await runner._verify_authenticated_session(mock_page, "https://example.com/dashboard")
    assert is_auth is False
