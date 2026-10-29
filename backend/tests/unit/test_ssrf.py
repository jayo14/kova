"""SSRF protection tests for BrowserSession and ActionExecutor navigate."""

import pytest

from app.engine.browser.session import _is_safe_url, _redact_url


class TestIsSafeUrl:
    def test_public_http_ok(self, monkeypatch):
        import socket
        monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ])
        assert _is_safe_url("http://example.com/path") is True

    def test_public_https_ok(self, monkeypatch):
        import socket
        monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ])
        assert _is_safe_url("https://example.com") is True

    def test_loopback_allowed_outside_production(self, monkeypatch):
        # Test env opts in via conftest (ALLOW_LOCALHOST=true).
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ALLOW_LOCALHOST", True)
        monkeypatch.setattr(settings, "ALLOW_LOCALHOST_TARGETS", "")
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


def test_mock_getaddrinfo_loopback(monkeypatch):
    """Host resolving to 127.0.0.1 via getaddrinfo is rejected."""
    import socket
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )
    assert _is_safe_url("http://attacker-controlled.com/ssrf") is False


def test_mock_getaddrinfo_metadata_ip(monkeypatch):
    """Host resolving to 169.254.169.254 via getaddrinfo is rejected."""
    import socket
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))],
    )
    assert _is_safe_url("http://rebind-to-metadata.com/latest") is False


def test_decimal_hex_and_cgnat_blocked():
    """Decimal, hex, IPv6-mapped, and 100.64.0.0/10 forms are rejected."""
    # 100.64.0.0/10 Carrier Grade NAT
    assert _is_safe_url("http://100.64.0.1/") is False
    assert _is_safe_url("http://100.127.255.254/") is False

    # Decimal integer representations of loopback and private IPs
    assert _is_safe_url("http://2130706433/", allow_loopback=False) is False  # 127.0.0.1
    assert _is_safe_url("http://2852039166/") is False  # 169.254.169.254
    assert _is_safe_url("http://167772161/") is False   # 10.0.0.1

    # Hex representations
    assert _is_safe_url("http://0x7f000001/", allow_loopback=False) is False # 127.0.0.1
    assert _is_safe_url("http://0xa9fea9fe/") is False # 169.254.169.254
    assert _is_safe_url("http://0x7f.0.0.1/", allow_loopback=False) is False

    # IPv6-mapped forms
    assert _is_safe_url("http://[::ffff:127.0.0.1]/", allow_loopback=False) is False
    assert _is_safe_url("http://[::ffff:169.254.169.254]/") is False
    assert _is_safe_url("http://[::ffff:10.0.0.1]/") is False


def test_ipv6_unique_local_and_mapped_addresses_blocked():
    assert _is_safe_url("http://[fc00::1]/", allow_loopback=False) is False
    assert _is_safe_url("http://[fe80::1]/", allow_loopback=False) is False
    assert _is_safe_url("http://[::ffff:192.168.1.1]/", allow_loopback=False) is False


def test_credentials_in_submitted_url_are_rejected():
    assert _is_safe_url("https://user:password@example.com/path") is False


def test_diagnostics_strip_credentials_and_query_values():
    assert _redact_url("https://user:secret@example.com/path?token=private#fragment") == "https://example.com/path"


class TestLocalhostPolicy:
    def test_default_denies_localhost(self, monkeypatch):
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ALLOW_LOCALHOST", False)
        assert _is_safe_url("http://localhost/admin") is False
        assert _is_safe_url("http://127.0.0.1/") is False
        assert _is_safe_url("http://[::1]/") is False

    def test_opt_in_allows_localhost_and_loopback_ips(self, monkeypatch):
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ALLOW_LOCALHOST", True)
        monkeypatch.setattr(settings, "ALLOW_LOCALHOST_TARGETS", "")
        assert _is_safe_url("http://localhost:5000/app") is True
        assert _is_safe_url("http://127.0.0.1:5000/") is True

    def test_allowlist_rejects_unlisted_local_targets(self, monkeypatch):
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ALLOW_LOCALHOST", True)
        monkeypatch.setattr(settings, "ALLOW_LOCALHOST_TARGETS", "localhost:8080")
        assert _is_safe_url("http://localhost:8080/") is True
        assert _is_safe_url("http://localhost:9090/") is False
        # Raw loopback form is subject to the same allowlist.
        assert _is_safe_url("http://127.0.0.1:8080/") is False

    def test_allowlist_bare_host_entry_covers_any_port(self, monkeypatch):
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ALLOW_LOCALHOST", True)
        monkeypatch.setattr(settings, "ALLOW_LOCALHOST_TARGETS", "localhost")
        assert _is_safe_url("http://localhost:8080/") is True
        assert _is_safe_url("http://localhost:9090/") is True

    def test_opt_in_does_not_open_private_ranges_or_rebinding(self, monkeypatch):
        import socket

        from app.config.settings import settings

        monkeypatch.setattr(settings, "ALLOW_LOCALHOST", True)
        monkeypatch.setattr(settings, "ALLOW_LOCALHOST_TARGETS", "")
        # Private ranges stay denied.
        assert _is_safe_url("http://10.0.0.1/") is False
        assert _is_safe_url("http://192.168.1.1/") is False
        # Hostname resolving to loopback (DNS rebinding) stays denied.
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
        )
        assert _is_safe_url("http://rebind-attacker.com/") is False


def test_settings_default_denies_localhost(monkeypatch):
    from app.config.settings import Settings

    monkeypatch.delenv("ALLOW_LOCALHOST", raising=False)
    assert Settings(_env_file=None).ALLOW_LOCALHOST is False


def test_settings_production_rejects_allow_localhost(monkeypatch):
    from cryptography.fernet import Fernet

    from app.config.settings import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOW_LOCALHOST", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "p" * 64)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="ALLOW_LOCALHOST cannot be enabled in production"):
        Settings(_env_file=None)

