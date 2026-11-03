"""Hosting platform wake and interstitial signature registry.

Detects when an infrastructure provider (Render, Heroku, Railway, Fly, Netlify,
Vercel, etc.) is serving a wake-up, cold-start, or platform-level error
interstitial rather than the user's actual application.

Principles:
1. Platform headers (via: 1.1 vegur, x-render-origin-server, server, etc.) and
   hostnames (*.onrender.com) only IDENTIFY the platform. They never indicate waking.
2. Render cold instances do not serve wake interstitials; they exhibit a "slow first byte"
   holding the connection (40s-75s) until the application answers.
3. Every production platform interstitial signature is marked "unverified" until backed by
   real captures supplied by the user. Unverified signatures never emit wake messages.
4. Synthetic signatures are labeled synthetic and used only for testing polling logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

# Platforms known to sleep/spin down free instances after inactivity
SLEEPING_FREE_INSTANCE_PLATFORMS: frozenset[str] = frozenset(
    {"Render", "Heroku", "Railway", "Fly.io"}
)


def identify_platform(
    url: str = "",
    headers: Mapping[str, str] | None = None,
) -> str | None:
    """Identify the hosting platform from hostname or response headers.

    Platform headers and hostnames ONLY identify the platform; they never
    indicate whether an instance is waking up.
    """
    normalized_headers = {k.lower(): v.lower() for k, v in (headers or {}).items()}
    url_lower = (url or "").lower()

    # 1. Post-response headers check
    # Render identification strictly uses rndr-id and x-render-origin-server.
    # Real responses have "server: cloudflare", so "server: render" is never checked.
    if (
        "rndr-id" in normalized_headers
        or "x-render-origin-server" in normalized_headers
    ):
        return "Render"
    if "x-heroku-queue-wait-time" in normalized_headers or "vegur" in normalized_headers.get("via", ""):
        return "Heroku"
    if "x-railway-request-id" in normalized_headers or normalized_headers.get("server") == "railway":
        return "Railway"
    if "fly-request-id" in normalized_headers or normalized_headers.get("server") == "fly":
        return "Fly.io"
    if (
        "x-vercel-id" in normalized_headers
        or "x-vercel-error" in normalized_headers
        or normalized_headers.get("server") == "vercel"
    ):
        return "Vercel"
    if "x-nf-request-id" in normalized_headers or normalized_headers.get("server") == "netlify":
        return "Netlify"

    # 2. Pre-response hostname check
    if ".onrender.com" in url_lower:
        return "Render"
    if ".herokuapp.com" in url_lower:
        return "Heroku"
    if ".railway.app" in url_lower:
        return "Railway"
    if ".fly.dev" in url_lower:
        return "Fly.io"
    if ".vercel.app" in url_lower:
        return "Vercel"
    if ".netlify.app" in url_lower:
        return "Netlify"

    return None


def is_sleeping_free_instance_platform(platform: str | None) -> bool:
    """Return True if the platform is known to sleep free instances after inactivity."""
    return bool(platform and platform in SLEEPING_FREE_INSTANCE_PLATFORMS)


def format_slow_first_byte_message(
    elapsed_s: float,
    platform: str | None,
    threshold_s: float = 20.0,
) -> str:
    """Format status message after response headers arrive.

    - "Waiting for the server to respond (Ns)": request sent, no response headers yet.
    - After headers arrive late (> 20s): "The server took Ns to respond."
      If on a platform known to sleep free instances, adds labeled inference:
      "Typical of a sleeping instance waking up." (phrased as likely, never fact).
    """
    sec = int(round(elapsed_s))
    if elapsed_s >= threshold_s:
        base = f"The server took {sec}s to respond."
        if is_sleeping_free_instance_platform(platform):
            return f"{base} (Typical of a sleeping instance waking up.)"
        return base
    return f"The server responded in {sec}s."


class TargetClassification(tuple):
    """Result of classifying a target document.

    Subclasses tuple for seamless backward compatibility with
    `is_backend, msg = classify_target_document(...)`.
    """

    def __new__(
        cls,
        is_invalid: bool,
        message: str,
        error_code: str | None = None,
        can_continue: bool = False,
    ):
        obj = super().__new__(cls, (is_invalid, message))
        obj.is_invalid = is_invalid
        obj.message = message
        obj.error_code = error_code
        obj.can_continue = can_continue
        return obj


def classify_target_document(
    status_code: int | None,
    headers: Mapping[str, str],
    body_text: str,
    title: str = "",
) -> TargetClassification:
    """Classify whether the root document is an error/debug/API backend, bot-challenge, or auth barrier.

    - Bot verification challenges (Cloudflare "Just a moment", Turnstile, CAPTCHA) -> BOT_BLOCKED.
    - HTTP 401 or 403 -> AUTH_REQUIRED.
    - Root 404/5xx, Django debug template, JSON body, bare gunicorn/nginx -> INVALID_TARGET (with can_continue=True).
    - Never reports 401/403 or bot challenges as "backend or error page".
    """
    normalized_headers = {k.lower(): v.lower() for k, v in headers.items()}
    text_lower = (body_text or "").lower()
    title_lower = (title or "").lower()
    content_type = normalized_headers.get("content-type", "")
    full_text = f"{title_lower} {text_lower}"

    status = status_code or 200

    # 1. Bot challenge check (Cloudflare, Turnstile, CAPTCHA, DDoS-GUARD)
    bot_challenge_markers = (
        "just a moment",
        "turnstile",
        "cf-chl-",
        "challenges.cloudflare.com",
        "attention required! | cloudflare",
        "checking your browser",
        "checking if the site connection is secure",
        "ddos-guard",
        "recaptcha",
        "hcaptcha",
        "security check to access",
        "verify you are human",
        "verify that you are human",
    )
    if any(marker in full_text for marker in bot_challenge_markers):
        return TargetClassification(
            True,
            "Bot verification challenge detected (Cloudflare/CAPTCHA). Automated access was blocked by the host.",
            error_code="BOT_BLOCKED",
            can_continue=False,
        )

    # 2. HTTP 401 / 403 status codes are reported as AUTH_REQUIRED, never "backend or error page"
    if status == 401:
        return TargetClassification(
            True,
            "This URL returned HTTP 401 (Authentication Required). Access to this application requires credentials.",
            error_code="AUTH_REQUIRED",
            can_continue=False,
        )
    if status == 403:
        # Check if Cloudflare 403 challenge
        if "cf-ray" in normalized_headers or "cloudflare" in normalized_headers.get("server", ""):
            if "cloudflare" in full_text or "forbidden" in full_text or "access denied" in full_text:
                return TargetClassification(
                    True,
                    "Bot verification challenge detected (Cloudflare/CAPTCHA). Automated access was blocked by the host.",
                    error_code="BOT_BLOCKED",
                    can_continue=False,
                )
        return TargetClassification(
            True,
            "This URL returned HTTP 403 (Access Denied / Forbidden). Access to this application requires authorization.",
            error_code="AUTH_REQUIRED",
            can_continue=False,
        )

    # 3. Status code check: 404/5xx at root is a non-application target (INVALID_TARGET)
    if status in (404, 500, 502, 503, 504):
        msg = f"This URL returned {status} at the root and looks like a backend or error page. Please check the URL and provide the web application address."
        return TargetClassification(True, msg, error_code="INVALID_TARGET", can_continue=True)

    # 4. Django debug template check (can happen at 404 or 500 or misconfigured debug route)
    django_debug_markers = (
        "using the urlconf defined in",
        "django tried these url patterns",
        "you're seeing this error because you have debug = true",
        "the empty path didn't match any of these",
        "didn't match any of these",
        "django version:",
    )
    if any(marker in text_lower for marker in django_debug_markers):
        msg = f"This URL returned {status} at the root and looks like a backend or error page. Please check the URL and provide the web application address."
        return TargetClassification(True, msg, error_code="INVALID_TARGET", can_continue=True)

    # 5. JSON body at root check (API backend rather than frontend web application)
    if "application/json" in content_type:
        msg = f"This URL returned {status} at the root and looks like a backend or error page. Please check the URL and provide the web application address."
        return TargetClassification(True, msg, error_code="INVALID_TARGET", can_continue=True)

    trimmed = body_text.strip()
    if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, (dict, list)):
                msg = f"This URL returned {status} at the root and looks like a backend or error page. Please check the URL and provide the web application address."
                return TargetClassification(True, msg, error_code="INVALID_TARGET", can_continue=True)
        except Exception:
            pass

    # 6. Bare server error pages (gunicorn, nginx, werkzeug, express)
    bare_server_markers = (
        "cannot get /",
        "502 bad gateway",
        "504 gateway time-out",
        "internal server error",
        "404 not found",
    )
    if any(m in text_lower for m in bare_server_markers):
        if any(h in normalized_headers.get("server", "") for h in ("nginx", "gunicorn", "caddy", "apache")) or "x-render-origin-server" in normalized_headers:
            msg = f"This URL returned {status} at the root and looks like a backend or error page. Please check the URL and provide the web application address."
            return TargetClassification(True, msg, error_code="INVALID_TARGET", can_continue=True)

    return TargetClassification(False, "", error_code=None, can_continue=False)



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
        ("x-render-origin-server", r".+"),
        ("rndr-id", r".+"),
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

    # Production platform interstitial signatures (unverified until backed by real user captures)
    # Note: Render uses the slow first-byte model (no wake interstitial exists; see render_cold_first_byte.txt)
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
