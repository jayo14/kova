"""Egress guard: URL safety policy for browser navigation.

Deterministic SSRF checks used by BrowserSession route interception,
navigate(), and lazy call sites (executor, email provider, crawler,
AI validator). Session re-exports the helpers for backward
compatibility; new code should import from this module.

DNS rebinding defense: evaluate_url() resolves a hostname exactly once
and returns the verified addresses inside the verdict. The route
handler pins plain-HTTP requests to that verified address (Host header
preserved), so Chromium never performs a second, attacker-influenced
lookup. HTTPS keeps its own TLS hostname verification and is not
rewritten.
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from app.config.settings import settings

# SSRF protection: block private/internal IP ranges.
_CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")
_METADATA_HOSTS = {"metadata.google.internal", "169.254.169.254"}


@dataclass(frozen=True)
class _Verdict:
    """Result of a single egress evaluation of one URL."""

    safe: bool
    scheme: str = ""
    host: str = ""
    port: int | None = None
    # Plain-HTTP requests are rewritten to this verified address; the
    # original authority goes into host_header so vhosts keep routing.
    # None = do not rewrite (HTTPS, IP literals, localhost, unsafe).
    pin_url: str | None = None
    host_header: str | None = None


def _redact_url(url: str) -> str:
    """Remove URL credentials and query values before storing diagnostic URLs."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunparse((parsed.scheme, host, parsed.path, parsed.params, "", ""))
    except Exception:
        return "[redacted URL]"


def _parse_raw_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse raw IP in standard, decimal integer, hex, or dotted-hex/octal forms."""
    h = host.strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass

    # Decimal integer IP (e.g. 2130706433)
    if h.isdigit():
        try:
            val = int(h)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            pass

    # Hex IP (e.g. 0x7f000001)
    if h.lower().startswith("0x"):
        try:
            val = int(h, 16)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            pass

    # Dotted hex/octal (e.g. 0x7f.0.0.1)
    parts = h.split(".")
    if len(parts) == 4:
        try:
            nums = [int(p, 0) for p in parts]
            if all(0 <= n <= 255 for n in nums):
                return ipaddress.IPv4Address(bytes(nums))
        except (ValueError, OverflowError):
            pass

    return None


def _is_ip_safe(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_loopback: bool) -> bool:
    """Check if resolved IP is safe from SSRF."""
    # Unmap IPv6-mapped IPv4 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if ip.is_loopback:
        return allow_loopback
    if (
        ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or ip in _CARRIER_GRADE_NAT
    ):
        return False

    return True


def evaluate_url(url: str, *, allow_loopback: bool | None = None) -> _Verdict:
    """Evaluate one URL for egress safety, resolving DNS at most once.

    Returns an unsafe verdict for non-HTTP(S) schemes, credentialled
    URLs, metadata hosts, and any hostname resolving to a private,
    loopback (unless explicitly allowed), link-local, reserved,
    multicast, unspecified, or 100.64.0.0/10 address. Handles decimal,
    hex, dotted-octal, and IPv6-mapped literal forms.

    Loopback is default-denied: it requires the ALLOW_LOCALHOST opt-in
    (validator-forced off in production) and, when ALLOW_LOCALHOST_TARGETS
    is set, a matching entry ("host" = any port, or "host:port").

    For safe plain-HTTP URLs with a hostname, pin_url/host_header carry
    the verified address for request pinning; callers must fall back to
    an unpinned request if overriding the URL is rejected.
    """
    if allow_loopback is None:
        # Default-deny: local targets only with explicit opt-in.
        allow_loopback = (
            getattr(settings, "ALLOW_LOCALHOST", False)
            and not settings.is_production
        )

    try:
        parsed = urlparse(url)
    except Exception:
        return _Verdict(False)

    if parsed.scheme not in ("http", "https"):
        return _Verdict(False)
    if parsed.username is not None or parsed.password is not None:
        return _Verdict(False)

    hostname = parsed.hostname or ""
    if not hostname:
        return _Verdict(False)

    host = hostname.lower()
    scheme = parsed.scheme
    port = parsed.port
    if host in _METADATA_HOSTS:
        return _Verdict(False, scheme=scheme, host=host, port=port)

    # Optional allowlist narrows loopback permission to specific local
    # targets: entries are "host" (any port) or "host:port".
    if allow_loopback:
        allowed = list(getattr(settings, "allow_localhost_targets_list", None) or [])
        if allowed:
            default_port = 443 if scheme == "https" else 80
            netloc = f"{host}:{port or default_port}"
            if not any(host == a or netloc == a for a in allowed):
                allow_loopback = False

    # Check for direct raw IP representations first (decimal, hex, etc.)
    raw_ip = _parse_raw_ip(host)
    if raw_ip is not None:
        # Connect target is already an address; no pin needed.
        return _Verdict(_is_ip_safe(raw_ip, allow_loopback), scheme=scheme, host=host, port=port)

    # For literal localhost: no second lookup and no rewrite — the name
    # is a local resolver fixture, not attacker-influenced DNS.
    if host == "localhost":
        try:
            # Explicit caller denial (production path) always wins over any
            # local-dev ALLOW_LOCALHOST opt-in.
            if not allow_loopback:
                return _Verdict(False, scheme=scheme, host=host, port=port)
            if getattr(settings, "ALLOW_LOCALHOST", False):
                # Target allowlist (if any) already applied above.
                return _Verdict(True, scheme=scheme, host=host, port=port)
            if allow_loopback and not getattr(settings, "is_production", False):
                return _Verdict(True, scheme=scheme, host=host, port=port)
            return _Verdict(False, scheme=scheme, host=host, port=port)
        except Exception:
            return _Verdict(allow_loopback, scheme=scheme, host=host, port=port)

    # Resolve hostname with socket.getaddrinfo (exactly once per URL).
    try:
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return _Verdict(False, scheme=scheme, host=host, port=port)
    except Exception:
        return _Verdict(False, scheme=scheme, host=host, port=port)

    if not addr_info:
        return _Verdict(False, scheme=scheme, host=host, port=port)

    # Reject if any resolved IP address is unsafe; keep first verified
    # address for pinning.
    pinned_ip: str | None = None
    is_loopback_host = host in ("localhost", "127.0.0.1", "::1")
    effective_allow_loopback = allow_loopback and is_loopback_host
    for info in addr_info:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return _Verdict(False, scheme=scheme, host=host, port=port)

        if not _is_ip_safe(ip, effective_allow_loopback):
            return _Verdict(False, scheme=scheme, host=host, port=port)

        if pinned_ip is None:
            pinned_ip = ip_str

    pin_url: str | None = None
    host_header: str | None = None
    if scheme == "http" and pinned_ip is not None:
        netloc = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
        if port and port != 80:
            netloc = f"{netloc}:{port}"
        pin_url = urlunparse((scheme, netloc, parsed.path, parsed.params, parsed.query, ""))
        default_port = 80
        host_header = host if not port or port == default_port else f"{host}:{port}"

    return _Verdict(
        True,
        scheme=scheme,
        host=host,
        port=port,
        pin_url=pin_url,
        host_header=host_header,
    )


def _is_safe_url(url: str, *, allow_loopback: bool | None = None) -> bool:
    """Check if a URL is safe to navigate to (SSRF protection).

    Thin wrapper over evaluate_url() for boolean call sites.
    """
    return evaluate_url(url, allow_loopback=allow_loopback).safe
