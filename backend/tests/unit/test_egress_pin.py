"""Unit tests for egress evaluate_url(): resolve-once pinning."""

import socket

import pytest

from app.config.settings import settings
from app.engine.browser.egress import evaluate_url


@pytest.fixture
def getaddrinfo_spy(monkeypatch):
    """Replace socket.getaddrinfo with a counting fake resolving one IPv4."""
    calls = {"count": 0, "host": None}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls["count"] += 1
        calls["host"] = host
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return calls


class TestResolveOncePinning:
    def test_http_hostname_pins_to_verified_ip(self, getaddrinfo_spy):
        v = evaluate_url("http://example.com/path?q=1")
        assert v.safe is True
        assert v.pin_url == "http://93.184.216.34/path?q=1"
        assert v.host_header == "example.com"
        # resolve-once: policy check and pin share one lookup
        assert getaddrinfo_spy["count"] == 1

    def test_non_default_port_preserved_in_pin_and_host_header(
        self, getaddrinfo_spy
    ):
        v = evaluate_url("http://example.com:8080/x")
        assert v.safe is True
        assert v.pin_url == "http://93.184.216.34:8080/x"
        assert v.host_header == "example.com:8080"
        assert getaddrinfo_spy["count"] == 1

    def test_default_port_omitted_from_host_header(self, getaddrinfo_spy):
        v = evaluate_url("http://example.com/")
        assert v.host_header == "example.com"
        assert ":80" not in v.pin_url

    def test_https_never_pinned(self, getaddrinfo_spy):
        v = evaluate_url("https://example.com/secure")
        assert v.safe is True
        assert v.pin_url is None
        assert v.host_header is None
        assert getaddrinfo_spy["count"] == 1

    def test_ip_literal_not_pinned(self):
        v = evaluate_url("http://93.184.216.34/x")
        assert v.safe is True
        assert v.pin_url is None

    def test_metadata_host_unsafe_without_resolution(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("metadata host must not resolve")

        monkeypatch.setattr(socket, "getaddrinfo", boom)
        v = evaluate_url("http://169.254.169.254/latest/meta-data/")
        assert v.safe is False
        v = evaluate_url("http://metadata.google.internal/computeMetadata/v1/")
        assert v.safe is False

    def test_localhost_default_denied(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("literal localhost must not resolve")

        monkeypatch.setattr(socket, "getaddrinfo", boom)
        # tests/conftest.py opts ALLOW_LOCALHOST in; flip it off to
        # observe the production default.
        monkeypatch.setattr(settings, "ALLOW_LOCALHOST", False)
        assert evaluate_url("http://localhost:8080/admin").safe is False

    def test_unresolvable_host_unsafe(self, monkeypatch):
        def fail(*a, **k):
            raise socket.gaierror("NXDOMAIN")

        monkeypatch.setattr(socket, "getaddrinfo", fail)
        assert evaluate_url("http://nonexistent.invalid/").safe is False

    def test_rebinding_window_closed_by_pin(self, monkeypatch):
        """The verified address from the single lookup IS the connect target."""
        seen = []

        def fake_getaddrinfo(host, port, *args, **kwargs):
            seen.append(host)
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        v = evaluate_url("http://rebind.attacker.test/")
        assert v.safe is True
        assert v.pin_url == "http://93.184.216.34/"
        assert seen == ["rebind.attacker.test"]

    def test_hostname_resolving_to_loopback_blocked_by_default(
        self, monkeypatch
    ):
        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        assert evaluate_url("http://localtest.me/").safe is False

    def test_ipv6_resolved_host_pins_with_brackets(self, monkeypatch):
        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0),
                ),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        v = evaluate_url("http://example.com/x")
        assert v.safe is True
        assert (
            v.pin_url
            == "http://[2606:2800:220:1:248:1893:25c8:1946]/x"
        )
