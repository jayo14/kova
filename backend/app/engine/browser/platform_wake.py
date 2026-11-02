"""Hosting platform wake and interstitial signature registry.

Detects when an infrastructure provider (Render, Heroku, Railway, Fly, Netlify,
Vercel, etc.) is serving a wake-up, cold-start, or platform-level error
interstitial rather than the user's actual application.

Detection is strictly signature-driven based on HTTP headers, status codes,
page title, and structural/text markers. Never guesses based on elapsed time.
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

        # 1. Status code check
        status_matched = False
        if self.status_codes:
            if status_code is not None and status_code in self.status_codes:
                status_matched = True
                matched_reasons.append(f"status={status_code}")
        else:
            status_matched = True

        # 2. Header pattern check
        header_matched = False
        for h_key, h_val_pattern in self.header_patterns:
            actual_val = normalized_headers.get(h_key.lower(), "")
            if actual_val and re.search(h_val_pattern.lower(), actual_val):
                header_matched = True
                matched_reasons.append(f"header:{h_key}={actual_val}")
                break

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

        # Url domain token as supporting evidence (e.g., onrender.com)
        domain_matched = False
        if f".onrender.com" in normalized_url and self.platform.lower() == "render":
            domain_matched = True
        elif f".herokuapp.com" in normalized_url and self.platform.lower() == "heroku":
            domain_matched = True
        elif f".railway.app" in normalized_url and self.platform.lower() == "railway":
            domain_matched = True
        elif f".fly.dev" in normalized_url and self.platform.lower() == "fly":
            domain_matched = True
        elif f".vercel.app" in normalized_url and self.platform.lower() == "vercel":
            domain_matched = True
        elif f".netlify.app" in normalized_url and self.platform.lower() == "netlify":
            domain_matched = True

        # Validation logic:
        # A platform wake requires strong corroboration. Header or domain match plus
        # wake body/title tokens, or specific provider error headers plus status code.
        if self.is_waking:
            # Wake detection
            has_provider_anchor = header_matched or domain_matched
            has_wake_content = (
                (title_matched or body_matched)
                and (
                    "waking" in normalized_body
                    or "waking" in normalized_title
                    or "spin down" in normalized_body
                    or "spun down" in normalized_body
                    or "starting up" in normalized_body
                    or "starting the" in normalized_body
                    or "cold start" in normalized_body
                    or "allocating compute" in normalized_body
                    or "preparing instance" in normalized_body
                )
            )
            if has_provider_anchor and (has_wake_content or (header_matched and body_matched)):
                return True, "; ".join(matched_reasons)
            if header_matched and title_matched and body_matched:
                return True, "; ".join(matched_reasons)
        else:
            # Platform error / gateway interstitial
            if header_matched and (status_matched or title_matched or body_matched):
                return True, "; ".join(matched_reasons)
            if domain_matched and status_matched and (title_matched or body_matched):
                return True, "; ".join(matched_reasons)

        return False, ""


PLATFORM_SIGNATURES: tuple[PlatformSignature, ...] = (
    # Render waking / spin down
    PlatformSignature(
        platform="Render",
        is_waking=True,
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
            "render dashboard",
            "starting the container",
        ),
    ),
    # Render gateway error
    PlatformSignature(
        platform="Render",
        is_waking=False,
        status_codes=frozenset({502, 503, 504}),
        header_patterns=(
            ("server", r"render"),
            ("x-render-origin-server", r".+"),
        ),
        title_tokens=("render", "service unavailable", "bad gateway"),
        body_tokens=("render", "failed to respond", "service unavailable"),
    ),
    # Heroku error / sleeping
    PlatformSignature(
        platform="Heroku",
        is_waking=False,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("via", r"vegur"),
            ("server", r"cowboy"),
            ("x-heroku-queue-wait-time", r".+"),
        ),
        title_tokens=("heroku | application error", "heroku | no such app", "heroku"),
        body_tokens=("an error occurred in the application and your page could not be served", "check your logs"),
    ),
    # Railway
    PlatformSignature(
        platform="Railway",
        is_waking=True,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("server", r"railway"),
            ("x-railway-request-id", r".+"),
        ),
        title_tokens=("railway", "application not responding"),
        body_tokens=("railway deployment is starting up", "starting up"),
    ),
    PlatformSignature(
        platform="Railway",
        is_waking=False,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("server", r"railway"),
            ("x-railway-request-id", r".+"),
        ),
        title_tokens=("railway - application not responding", "railway"),
        body_tokens=("application failed to respond", "railway"),
    ),
    # Fly.io
    PlatformSignature(
        platform="Fly.io",
        is_waking=True,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("server", r"fly"),
            ("fly-request-id", r".+"),
        ),
        title_tokens=("503 service unavailable", "fly.io"),
        body_tokens=("machine starting up", "allocating compute"),
    ),
    PlatformSignature(
        platform="Fly.io",
        is_waking=False,
        status_codes=frozenset({502, 503}),
        header_patterns=(
            ("server", r"fly"),
            ("fly-request-id", r".+"),
        ),
        title_tokens=("service unavailable",),
        body_tokens=("no healthy machine available",),
    ),
    # Vercel
    PlatformSignature(
        platform="Vercel",
        is_waking=False,
        status_codes=frozenset({502, 504}),
        header_patterns=(
            ("server", r"vercel"),
            ("x-vercel-id", r".+"),
            ("x-vercel-error", r".+"),
        ),
        title_tokens=("504: gateway_timeout", "502: bad_gateway", "vercel"),
        body_tokens=("serverless function has timed out", "function_invocation_timeout"),
    ),
    # Netlify
    PlatformSignature(
        platform="Netlify",
        is_waking=False,
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
    message: str | None = None
    matched_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "platform": self.platform,
            "is_waking": self.is_waking,
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

    Returns PlatformWakeResult with matched=True ONLY when verified by
    concrete platform headers, status, or structural markers.
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
                message=msg,
                matched_by=reason,
            )

    return PlatformWakeResult(matched=False)
