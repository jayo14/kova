"""SSRF protection tests for BrowserSession and ActionExecutor navigate."""

import pytest

from app.engine.browser.session import _is_safe_url


class TestIsSafeUrl:
    def test_public_http_ok(self):
        assert _is_safe_url("http://example.com/path") is True

    def test_public_https_ok(self):
        assert _is_safe_url("https://example.com") is True

    def test_loopback_allowed_outside_production(self):
        # Default: not production → local targets usable (integration tests)
        assert _is_safe_url("http://localhost/admin") is True
        assert _is_safe_url("http://127.0.0.1/") is True
        assert _is_safe_url("http://[::1]/") is True

    def test_loopback_blocked_in_production(self):
        assert _is_safe_url("http://localhost/admin", allow_loopback=False) is False
        assert _is_safe_url("http://127.0.0.1/", allow_loopback=False) is False
        assert _is_safe_url("http://[::1]/", allow_loopback=False) is False

    def test_private_ranges_blocked(self):
        assert _is_safe_url("http://10.0.0.1/") is False
        assert _is_safe_url("http://192.168.1.1/") is False
        assert _is_safe_url("http://172.16.0.1/") is False

    def test_file_scheme_blocked(self):
        assert _is_safe_url("file:///etc/passwd") is False

    def test_ftp_scheme_blocked(self):
        assert _is_safe_url("ftp://example.com") is False

    def test_empty_blocked(self):
        assert _is_safe_url("") is False

    def test_no_host_blocked(self):
        assert _is_safe_url("http://") is False

    def test_metadata_host_blocked(self):
        assert _is_safe_url("http://metadata.google.internal/") is False
        assert _is_safe_url("http://169.254.169.254/latest/meta-data/") is False


@pytest.mark.asyncio
async def test_navigate_blocks_unsafe_url(monkeypatch):
    from app.engine.browser.session import BrowserSession

    browser = BrowserSession()
    # Don't start real browser — navigate should fail before goto
    with pytest.raises(ValueError, match="unsafe"):
        await browser.navigate("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_executor_navigate_blocks_unsafe():
    from app.engine.browser.executor import ActionExecutor
    from app.engine.browser.actions import Action, ActionType, ActionTarget, ActionValidationError

    # Build action without needing a real page for pre-check
    action = Action(type=ActionType.NAVIGATE, value="http://169.254.169.254/latest/meta-data/")
    # Executor's _execute_action checks safety before page.goto
    executor = ActionExecutor.__new__(ActionExecutor)
    executor.page = None  # type: ignore

    with pytest.raises(ActionValidationError) as exc:
        await executor._execute_action(action)
    assert "unsafe" in str(exc.value).lower() or "blocked" in str(exc.value).lower()
