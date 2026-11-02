"""Hosting platform wake and interstitial signature registry.

Detects when an infrastructure provider (Render, Heroku, Railway, Fly, Netlify,
Vercel, etc.) is serving a wake-up, cold-start, or platform-level error
interstitial rather than the user's actual application.

Principles:
1. Platform headers (via: 1.1 vegur, x-render-origin-server, server, etc.)
   only IDENTIFY the platform. They never match on headers alone.
2. A "host is waking up" message requires a platform match AND a wake state
   (interstitial title/body, or a platform error status such as 502/503/504
   with a known wake body).
3. Every production platform signature is marked "unverified" until backed by
   real captures supplied by the user. Unverified signatures never emit wake messages.
4. Synthetic signatures are labeled synthetic and used only for testing polling logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PlatformSignature:
    """Signature definition for a hosting platform's wake or interstitial state."""

    platform: str
    is_waking: bool
    verified: bool = False  # Mark unverified until real captures are provided
    is_synthetic: bool = False  # Explicitly labeled synthetic for test fixtures
    status_codes: frozenset[int] = field(default_factory=frozenset)
    header_patterns: tuple[tuple[str, str], ...] = ()
    title_tokens: tuple[str, ...] = ()
    body_tokens: tuple[str, ...] = ()
    require_all_token_types: bool = False

    def matches(
        self,
        headers: Mapping[str, str],
        status_code: int | None,
        title: str,
        body_text: str,
        url: str = "",
    ) -> tuple[bool, str]:
        normalized_headers = {k.lower(): v.lower() for k, v in headers.items()}
        normalized_title = (title or "").lower()
        normalized_body = (body_text or "").lower()
        normalized_url = (url or "").lower()

        matched_reasons: list[str] = []

        # 1. Header pattern check (Platform Identification Only)
        header_matched = False
        for h_key, h_val_pattern in self.header_patterns:
            actual_val = normalized_headers.get(h_key.lower(), "")
            if actual_val and re.search(h_val_pattern.lower(), actual_val):
                header_matched = True
                matched_reasons.append(f"header:{h_key}={actual_val}")
                break

        # Url domain token as supporting platform identification evidence
        domain_matched = False
        if ".onrender.com" in normalized_url and self.platform.lower() == "render":
            domain_matched = True
        elif ".herokuapp.com" in normalized_url and self.platform.lower() == "heroku":
            domain_matched = True
        elif ".railway.app" in normalized_url and self.platform.lower() == "railway":
            domain_matched = True
        elif ".fly.dev" in normalized_url and self.platform.lower() == "fly":
            domain_matched = True
        elif ".vercel.app" in normalized_url and self.platform.lower() == "vercel":
            domain_matched = True
        elif ".netlify.app" in normalized_url and self.platform.lower() == "netlify":
            domain_matched = True

        platform_identified = header_matched or domain_matched
        if not platform_identified:
            return False, "platform_not_identified"

        # 2. Status code check
        status_matched = False
        if self.status_codes:
            if status_code is not None and status_code in self.status_codes:
                status_matched = True
                matched_reasons.append(f"status={status_code}")
        else:
            status_matched = True

        # 3. Title token check
        title_matched = False
        for tok in self.title_tokens:
            if tok.lower() in normalized_title:
                title_matched = True
                matched_reasons.append(f"title_token='{tok}'")
                break

        # 4. Body token check
        body_matched = False
        for tok in self.body_tokens:
            if tok.lower() in normalized_body:
                body_matched = True
                matched_reasons.append(f"body_token='{tok}'")
                break

        # Amendment 1: Never match on headers alone!
        # A "host is waking up" message requires a platform match AND a wake state
        # (interstitial title/body, or a platform error status 502/503/504 with a known wake body).
        wake_markers = (
            "waking",
            "spin down",
            "spun down",
            "starting up",
            "starting the container",
            "cold start",
            "allocating compute",
            "preparing instance",
        )
        has_wake_body_text = any(m in normalized_body for m in wake_markers) or any(m in normalized_title for m in wake_markers)

        if self.is_waking:
            wake_state_present = (title_matched or body_matched) and (
                has_wake_body_text
                or (status_code in (502, 503, 504) and (title_matched or body_matched))
            )
            if not wake_state_present:
                return False, "headers_only_no_wake_state"

            # Amendment 2: Do not emit wake messages for unverified signatures.
            # Only verified or explicitly synthetic signatures match for wake messages.
            if not self.verified and not self.is_synthetic:
                return False, "unverified_platform_signature"

            return True, "; ".join(matched_reasons)
        else:
            # Platform infrastructure error
            if (status_matched and (title_matched or body_matched)) or (title_matched and body_matched):
                if not self.verified and not self.is_synthetic:
                    return False, "unverified_platform_signature"
                return True, "; ".join(matched_reasons)

        return False, ""


# Synthetic Render fixture signature for testing polling logic only (Amendment 2)
SYNTHETIC_RENDER_WAKE_SIGNATURE = PlatformSignature(
    platform="Render",
    is_waking=True,
    verified=False,
    is_synthetic=True,
    status_codes=frozenset({200, 502, 503, 504}),
    header_patterns=(
        ("server", r"render"),
        ("x-render-origin-server", r".+"),
    ),
    title_tokens=("service waking up", "render", "free instance", "application loading"),
    body_tokens=(
        "free instance has spun down",
        "your free instance is waking up",
        "spin down due to inactivity",
        "starting the container",
        "allocating compute",
        "service waking up",
    ),
)


PLATFORM_SIGNATURES: tuple[PlatformSignature, ...] = (
    # Synthetic test fixture (strictly labeled for testing polling logic)
    SYNTHETIC_RENDER_WAKE_SIGNATURE,

    # Real platform signatures marked unverified until backed by real user captures
    PlatformSignature(
        platform="Render",
        is_waking=True,
        verified=False,
        is_synthetic=False,
        status_codes=frozenset({200, 502, 503, 504}),
        header_patterns=(
            ("server", r"render"),
            ("x-render-origin-server", r".+"),
        ),
        title_tokens=("service waking up", "render", "free instance"),
        body_tokens=(
            "free instance has spun down",
            "your free instance is waking up",
            "spin down due to inactivity",
            "starting the container",
        ),
    ),
    PlatformSignature(
        platform="Heroku",
        is_waking=False,
        verified=False,
        is_synthetic=False,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("via", r"vegur"),
            ("server", r"cowboy"),
            ("x-heroku-queue-wait-time", r".+"),
        ),
        title_tokens=("heroku | application error", "heroku | no such app"),
        body_tokens=("an error occurred in the application", "check your logs"),
    ),
    PlatformSignature(
        platform="Railway",
        is_waking=True,
        verified=False,
        is_synthetic=False,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("server", r"railway"),
            ("x-railway-request-id", r".+"),
        ),
        title_tokens=("railway", "application not responding"),
        body_tokens=("railway deployment is starting up", "starting up"),
    ),
    PlatformSignature(
        platform="Fly.io",
        is_waking=True,
        verified=False,
        is_synthetic=False,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("server", r"fly"),
            ("fly-request-id", r".+"),
        ),
        title_tokens=("503 service unavailable", "fly.io"),
        body_tokens=("machine starting up", "allocating compute"),
    ),
    PlatformSignature(
        platform="Vercel",
        is_waking=False,
        verified=False,
        is_synthetic=False,
        status_codes=frozenset({502, 504}),
        header_patterns=(
            ("server", r"vercel"),
            ("x-vercel-id", r".+"),
            ("x-vercel-error", r".+"),
        ),
        title_tokens=("504: gateway_timeout", "502: bad_gateway", "vercel"),
        body_tokens=("serverless function has timed out", "function_invocation_timeout"),
    ),
    PlatformSignature(
        platform="Netlify",
        is_waking=False,
        verified=False,
        is_synthetic=False,
        status_codes=frozenset({502, 504}),
        header_patterns=(
            ("server", r"netlify"),
            ("x-nf-request-id", r".+"),
        ),
        title_tokens=("netlify - bad gateway", "bad gateway"),
        body_tokens=("netlify function execution timed out", "failed to boot"),
    ),
)


@dataclass(frozen=True, slots=True)
class PlatformWakeResult:
    """Result of platform wake / interstitial signature evaluation."""

    matched: bool
    platform: str | None = None
    is_waking: bool = False
    verified: bool = False
    is_synthetic: bool = False
    message: str | None = None
    matched_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "platform": self.platform,
            "is_waking": self.is_waking,
            "verified": self.verified,
            "is_synthetic": self.is_synthetic,
            "message": self.message,
            "matched_by": self.matched_by,
        }


def detect_platform_wake(
    headers: Mapping[str, str],
    status_code: int | None,
    title: str,
    body_text: str,
    url: str = "",
) -> PlatformWakeResult:
    """Evaluate response and page content against platform signatures.

    Headers alone only identify the platform. A wake result is returned ONLY
    when verified platform identity is corroborated by wake title or body state.
    Unverified signatures do not emit wake messages.
    """
    for sig in PLATFORM_SIGNATURES:
        matched, reason = sig.matches(headers, status_code, title, body_text, url)
        if matched:
            if sig.is_waking:
                msg = f"The hosting service ({sig.platform}) is waking up"
            else:
                msg = f"The hosting platform ({sig.platform}) returned an infrastructure error"
            return PlatformWakeResult(
                matched=True,
                platform=sig.platform,
                is_waking=sig.is_waking,
                verified=(sig.verified or sig.is_synthetic),
                is_synthetic=sig.is_synthetic,
                message=msg,
                matched_by=reason,
            )

    return PlatformWakeResult(matched=False)
