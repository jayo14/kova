"""Deterministic page-readiness and page-identity classification.

This module answers one question before discovery runs: *is the page we are
looking at the application the user asked Kova to explore, and is that
application actually ready?*

Hosting providers (Render, Heroku, Railway, ...) serve branded sleep / warm-up
interstitials from the application's own hostname. Those pages are reachable,
load quickly and often contain a button, so navigation-level checks alone
cannot tell them apart from a real application. Every decision here therefore
combines structural evidence (controls, navigation, headings, forms), textual
evidence acting as support only, redirect history and HTTP status. A single
keyword, title or button is never sufficient on its own.

No LLM or vision model is used: classification is fully deterministic so that
discovery results are reproducible and testable.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "RETRYABLE_STATES",
    "PageReadiness",
    "PageSignals",
    "ReadinessAssessment",
    "ReadinessWaiter",
    "UrlIntegrity",
    "assess_url_integrity",
    "classify_page",
    "is_infrastructure_control",
]


class PageReadiness(StrEnum):
    """What the observed page actually is."""

    APPLICATION_READY = "application_ready"
    APPLICATION_LOADING = "application_loading"
    HOSTING_INTERSTITIAL = "hosting_interstitial"
    AUTHENTICATION_REQUIRED = "authentication_required"
    ACCESS_DENIED = "access_denied"
    PROXY_OR_GATEWAY_ERROR = "proxy_or_gateway_error"
    APPLICATION_ERROR = "application_error"
    BROWSER_ERROR = "browser_error"
    UNKNOWN_PAGE = "unknown_page"


RETRYABLE_STATES: frozenset[PageReadiness] = frozenset(
    {PageReadiness.APPLICATION_LOADING, PageReadiness.HOSTING_INTERSTITIAL}
)

# Providers whose branding can appear on infrastructure pages. Presence alone is
# never enough: the structural rules below must also agree.
_PROVIDER_TOKENS: tuple[str, ...] = (
    "render",
    "onrender",
    "heroku",
    "railway",
    "vercel",
    "netlify",
    "fly.io",
    "flyio",
    "cloudflare",
    "digitalocean",
    "aws amplify",
    "azure static",
)

# Generic words that carry no application identity on their own.
_GENERIC_IDENTITY_TOKENS: frozenset[str] = frozenset(
    {
        "www",
        "com",
        "net",
        "org",
        "io",
        "app",
        "web",
        "site",
        "home",
        "index",
        "main",
        "page",
        "localhost",
        "http",
        "https",
        "onrender",
        "herokuapp",
        "railway",
        "vercel",
        "netlify",
        "fly",
        "cloudflare",
        "digitalocean",
        "amplify",
    }
)

_GENERIC_TITLES: frozenset[str] = frozenset(
    {
        "",
        "home",
        "index",
        "app",
        "application",
        "welcome",
        "loading",
        "please wait",
        "untitled",
        "document",
        "new tab",
        "about:blank",
    }
)

_WAKE_LANGUAGE: tuple[str, ...] = (
    "waking up",
    "wake up",
    "waking",
    "sleeping",
    "spun down",
    "spin down",
    "starting up",
    "starting the",
    "booting",
    "cold start",
    "this may take",
    "takes a few seconds",
    "few moments",
    "in a moment",
    "taking a little longer",
    "almost there",
    "deploying",
    "deployment in progress",
    "building your",
    "please wait",
    "incoming http request",
    "service waking up",
    "service is waking",
    "service is starting",
    "allocating compute",
    "allocating compute resources",
    "preparing instance",
    "preparing instance for initialization",
    "container starting",
    "spinning up",
    "resuming service",
    "server is starting",
    "server waking up",
    "free instance",
    "spin down due to inactivity",
)

_LOADING_LANGUAGE: tuple[str, ...] = (
    "loading",
    "please wait",
    "initializing",
    "initialising",
    "preparing",
    "starting",
    "just a moment",
    "hang tight",
)

_INFRA_ERROR_LANGUAGE: tuple[str, ...] = (
    "service unavailable",
    "application error",
    "application failed to respond",
    "internal server error",
    "bad gateway",
    "gateway timeout",
    "this site can't be reached",
    "this page isn't working",
    "no application is running",
    "application not found",
    "deployment failed",
    "build failed",
    "something went wrong on our end",
    "we're experiencing technical difficulties",
)

_INFRA_CONTROL_LANGUAGE: tuple[str, ...] = (
    "wake up",
    "wake the",
    "try waking",
    "restart",
    "redeploy",
    "retry deploy",
    "check deployment",
    "view logs",
    "render dashboard",
    "open dashboard",
    "start building on",
    "start building",
    "cloud dashboard",
    "service dashboard",
    "view deployment",
    "infrastructure status",
)

_ACCESS_DENIED_LANGUAGE: tuple[str, ...] = (
    "access denied",
    "access forbidden",
    "forbidden",
    "not authorized",
    "unauthorized",
    "permission denied",
    "you don't have permission",
    "you do not have permission",
    "request blocked",
    "403 forbidden",
)

_ERROR_TITLE_LANGUAGE: tuple[str, ...] = (
    "500",
    "502",
    "503",
    "504",
    "error",
    "unavailable",
    "forbidden",
    "denied",
    "not found",
)

_BROAD_SELECTOR_FRAGMENTS: tuple[str, ...] = (
    "a, button",
    "div, section, p",
    "main, [role='main'], header, footer, body",
    "h1, h2, [role='heading']",
)


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def _contains_any(haystack: str, needles: Sequence[str]) -> list[str]:
    return [needle for needle in needles if needle in haystack]


def _host_of(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _registrable_label(host: str) -> str:
    """Return the first meaningful host label (``huntly-0pgj.onrender.com`` -> ``huntly``)."""
    labels = [label for label in host.split(".") if label]
    for label in labels:
        if label not in _GENERIC_IDENTITY_TOKENS and len(label) > 2:
            return label
    return labels[0] if labels else ""


def _host_identity_tokens(host: str) -> list[str]:
    tokens: list[str] = []
    for label in host.split("."):
        if not label or label in _GENERIC_IDENTITY_TOKENS:
            continue
        cleaned = "".join(ch for ch in label if ch.isalnum())
        if len(cleaned) < 3:
            continue
        tokens.append(cleaned)
        # Handle common startup domain prefixes (e.g. getpresently -> presently)
        for prefix in ("get", "try", "use", "join", "app", "meet", "go"):
            if cleaned.startswith(prefix) and len(cleaned) > len(prefix) + 2:
                sub = cleaned[len(prefix):]
                if sub not in tokens:
                    tokens.append(sub)
        # Split provider-generated suffixes like "huntly-0pgj" / "myapp-7f9c".
        for part in label.replace("_", "-").split("-"):
            part = "".join(ch for ch in part if ch.isalnum())
            if (
                len(part) >= 3
                and part not in _GENERIC_IDENTITY_TOKENS
                and part != cleaned
            ):
                tokens.append(part)
    return tokens


def _title_tokens(title: str | None) -> list[str]:
    raw = _normalize(title)
    if raw in _GENERIC_TITLES:
        return []
    tokens: list[str] = []
    for chunk in raw.replace("|", " ").replace("-", " ").replace(":", " ").split():
        cleaned = "".join(ch for ch in chunk if ch.isalnum())
        if len(cleaned) >= 3 and cleaned not in _GENERIC_IDENTITY_TOKENS:
            tokens.append(cleaned)
    return tokens


@dataclass(slots=True)
class PageSignals:
    """Everything the classifier is allowed to know about one observation."""

    requested_url: str = ""
    observed_url: str = ""
    title: str = ""
    body_text: str = ""
    http_status: int | None = None
    redirect_chain: list[str] = field(default_factory=list)
    interactive_count: int = 0
    form_count: int = 0
    link_count: int = 0
    heading_count: int = 0
    nav_item_count: int = 0
    has_password_field: bool = False
    has_email_field: bool = False
    browser_error: str | None = None

    @property
    def host(self) -> str:
        return _host_of(self.observed_url or self.requested_url)

    @property
    def text_length(self) -> int:
        return len(self.body_text.strip())


@dataclass(slots=True)
class UrlIntegrity:
    """Relationship between the URL the user supplied and the page we observed."""

    aligned: bool
    reason: str
    requested_host: str = ""
    observed_host: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aligned": self.aligned,
            "reason": self.reason,
            "requested_host": self.requested_host,
            "observed_host": self.observed_host,
        }


@dataclass(slots=True)
class ReadinessAssessment:
    """Classification result with the evidence that produced it."""

    state: PageReadiness
    reason: str
    confidence: float
    target_url: str
    observed_url: str
    category: str | None = None
    identity: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    uncertainty: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.state is PageReadiness.APPLICATION_READY

    @property
    def retryable(self) -> bool:
        return self.state in RETRYABLE_STATES

    def to_dict(self) -> dict[str, Any]:
        """Sanitized payload safe to persist or send to the frontend.

        Page body text never leaves the backend; only short evidence strings and
        structural counts are exposed.
        """
        return {
            "state": self.state.value,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
            "target_url": self.target_url,
            "observed_url": self.observed_url,
            "category": self.category,
            "identity": self.identity,
            "redirect_chain": list(self.redirect_chain),
            "evidence": {key: list(values) for key, values in self.evidence.items()},
            "uncertainty": self.uncertainty,
            "retryable": self.retryable,
            "is_ready": self.is_ready,
        }


def assess_url_integrity(
    requested_url: str,
    final_url: str,
    redirect_chain: Sequence[str] | None = None,
    *,
    allow_cross_origin: bool = False,
) -> UrlIntegrity:
    """Check whether navigation stayed on the host the user asked for."""
    requested_host = _host_of(requested_url)
    observed_host = _host_of(final_url)
    if not requested_host or not observed_host:
        return UrlIntegrity(
            aligned=False,
            reason="Could not determine the requested or observed host",
            requested_host=requested_host,
            observed_host=observed_host,
        )
    if requested_host == observed_host:
        return UrlIntegrity(
            True,
            "Observed host matches the requested host",
            requested_host,
            observed_host,
        )
    if (
        observed_host == f"www.{requested_host}"
        or requested_host == f"www.{observed_host}"
    ):
        return UrlIntegrity(
            True,
            "Observed host matches apart from a www prefix",
            requested_host,
            observed_host,
        )
    if allow_cross_origin:
        return UrlIntegrity(
            aligned=True,
            reason=f"Cross-origin redirect from {requested_host} to {observed_host} was allowed",
            requested_host=requested_host,
            observed_host=observed_host,
        )
    hops = [requested_host]
    hops.extend(h for h in (_host_of(u) for u in redirect_chain or []) if h)
    hops.append(observed_host)
    chain = " -> ".join(dict.fromkeys(hops))
    return UrlIntegrity(
        aligned=False,
        reason=f"Navigation left the requested host: {chain}",
        requested_host=requested_host,
        observed_host=observed_host,
    )


def _evidence(signals: PageSignals) -> dict[str, list[str]]:
    text = _normalize(signals.body_text)
    title = _normalize(signals.title)
    host = signals.host
    return {
        "url": [u for u in [signals.requested_url, signals.observed_url] if u],
        "host": [host] if host else [],
        "title": [signals.title.strip()] if signals.title.strip() else [],
        "http_status": [str(signals.http_status)]
        if signals.http_status is not None
        else [],
        "redirects": [u for u in signals.redirect_chain if u],
        "providers": _contains_any(f"{host} {title} {text}", _PROVIDER_TOKENS),
        "wake_language": _contains_any(text, _WAKE_LANGUAGE)[:4],
        "loading_language": _contains_any(text, _LOADING_LANGUAGE)[:4],
        "error_language": _contains_any(text, _INFRA_ERROR_LANGUAGE)[:4],
        "provider_controls": _contains_any(text, _INFRA_CONTROL_LANGUAGE)[:4],
        "access_denied_language": _contains_any(text, _ACCESS_DENIED_LANGUAGE)[:4],
        "structure": [
            f"interactive={signals.interactive_count}",
            f"forms={signals.form_count}",
            f"links={signals.link_count}",
            f"headings={signals.heading_count}",
            f"nav_items={signals.nav_item_count}",
            f"password_field={signals.has_password_field}",
            f"email_field={signals.has_email_field}",
            f"text_chars={signals.text_length}",
        ],
    }


def _identity_match(signals: PageSignals) -> tuple[bool, str | None]:
    """Decide whether page identity is grounded in the host or page itself."""
    tokens = _host_identity_tokens(signals.host)
    norm_title = _normalize(signals.title)
    haystack = f"{norm_title} {_normalize(signals.body_text[:2000])}"
    for token in tokens:
        if token in haystack:
            return True, token
    for word in norm_title.split():
        cleaned_word = "".join(ch for ch in word if ch.isalnum())
        if len(cleaned_word) >= 4 and any(cleaned_word in t for t in tokens):
            return True, cleaned_word
    return False, tokens[0] if tokens else None


def _provider_context(signals: PageSignals, text: str, title: str) -> tuple[bool, bool]:
    """Return (provider_branded, provider_control_present)."""
    host = signals.host
    providers = _contains_any(f"{host} {providers_text(signals)}", _PROVIDER_TOKENS)
    provider_branded = bool(providers)
    provider_control = bool(_contains_any(f"{title} {text}", _INFRA_CONTROL_LANGUAGE))
    return provider_branded, provider_control


def providers_text(signals: PageSignals) -> str:
    return f"{_normalize(signals.title)} {_normalize(signals.body_text[:4000])}"


def is_infrastructure_control(label: str, surrounding_text: str = "") -> bool:
    """Return True if a control text belongs to infrastructure/hosting provider rather than application."""
    norm = _normalize(label)
    if not norm:
        return False
    # If it's a URL, only flag if it navigates to an external provider dashboard/marketing domain
    if norm.startswith("http://") or norm.startswith("https://"):
        try:
            parsed = urlparse(norm)
            host = (parsed.hostname or "").lower()
            if any(
                host == p or host.endswith(f".{p}")
                for p in (
                    "render.com",
                    "railway.app",
                    "heroku.com",
                    "fly.io",
                    "vercel.com",
                    "netlify.com",
                    "cloudflare.com",
                )
            ):
                return True
        except ValueError:
            pass
        return False

    # Specific infrastructure phrases
    if any(ctrl in norm for ctrl in _INFRA_CONTROL_LANGUAGE):
        return True

    # Label mentioning provider by name as a distinct word combined with provider-level action
    for p in _PROVIDER_TOKENS:
        if re.search(r"\b" + re.escape(p) + r"\b", norm):
            if any(
                action in norm
                for action in (
                    "start building",
                    "build on",
                    "dashboard",
                    "console",
                    "logs",
                    "deploy",
                    "status",
                    "wake up",
                    "waking",
                    "hosted on",
                    "powered by",
                )
            ):
                return True
    return False


def _looks_like_hosting_interstitial(
    signals: PageSignals, text: str, title: str
) -> tuple[bool, str]:
    provider_branded, provider_control = _provider_context(signals, text, title)
    wake = _contains_any(text, _WAKE_LANGUAGE)
    short_body = signals.text_length < 1500
    no_app_nav = signals.nav_item_count < 2 and signals.link_count < 5
    low_controls = signals.interactive_count <= 6

    if provider_branded and wake and (low_controls or no_app_nav):
        return True, "Hosting provider page describes a sleeping or waking application"
    if wake and (low_controls or no_app_nav):
        return True, "Page describes a waking or sleeping infrastructure container"
    if provider_branded and short_body and no_app_nav and low_controls:
        return True, "Hosting provider page with no application navigation or controls"
    if provider_control and (signals.http_status or 0) >= 500:
        return (
            True,
            "Hosting provider control surfaced while the service is unavailable",
        )
    if provider_control and short_body and no_app_nav:
        return True, "Hosting provider control without an application shell"
    if provider_branded and (signals.http_status or 0) >= 500 and short_body:
        return True, "Hosting provider error page in place of the application"
    return False, ""


def _looks_like_auth(signals: PageSignals, auth_kind: str | None) -> bool:
    if signals.has_password_field:
        return True
    if auth_kind and _normalize(auth_kind) not in ("", "unknown"):
        # A real authentication challenge carries an email field or a form.
        return True
    path = urlparse(signals.observed_url).path.lower()
    if any(p in path for p in ("/login", "/signin", "/sign-in", "/signup", "/sign-up", "/register", "/auth/")):
        return True
    return False


def _looks_like_loading(signals: PageSignals, text: str, title: str) -> bool:
    loading = _contains_any(f"{title} {text}", _LOADING_LANGUAGE)
    if not loading:
        return False
    sparse = signals.heading_count <= 1 and signals.interactive_count <= 4
    return sparse or signals.text_length < 400


def _looks_like_access_denied(signals: PageSignals, text: str) -> bool:
    if signals.http_status in (401, 403):
        return True
    denied = _contains_any(
        f"{_normalize(signals.title)} {text}", _ACCESS_DENIED_LANGUAGE
    )
    return bool(denied) and signals.text_length < 1000


def _looks_like_app_error(signals: PageSignals, text: str, title: str) -> bool:
    if signals.browser_error:
        return False
    errors = _contains_any(f"{title} {text}", _INFRA_ERROR_LANGUAGE)
    title_error = (
        any(marker in title for marker in _ERROR_TITLE_LANGUAGE)
        and signals.text_length < 600
    )
    return bool(errors or title_error)


def _readiness_score(
    signals: PageSignals, identity_matched: bool
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if identity_matched:
        score += 1
        reasons.append("identity")
    if signals.nav_item_count >= 2 or signals.link_count >= 5:
        score += 1
        reasons.append("navigation")
    if signals.heading_count >= 2:
        score += 1
        reasons.append("headings")
    if signals.interactive_count >= 3 or signals.form_count >= 1:
        score += 1
        reasons.append("controls")
    return score, reasons


def classify_page(
    signals: PageSignals,
    *,
    auth_kind: str | None = None,
    previous: ReadinessAssessment | None = None,
    allow_cross_origin_redirect: bool = False,
) -> ReadinessAssessment:
    """Classify a single observation of the target page."""
    title = _normalize(signals.title)
    text = _normalize(signals.body_text)
    evidence = _evidence(signals)
    integrity = assess_url_integrity(
        signals.requested_url,
        signals.observed_url,
        signals.redirect_chain,
        allow_cross_origin=allow_cross_origin_redirect,
    )
    identity_matched, identity_token = _identity_match(signals)

    def result(
        state: PageReadiness,
        reason: str,
        confidence: float,
        *,
        category: str | None = None,
        uncertainty: str | None = None,
        identity: str | None = None,
    ) -> ReadinessAssessment:
        return ReadinessAssessment(
            state=state,
            reason=reason,
            confidence=confidence,
            target_url=signals.requested_url,
            observed_url=signals.observed_url,
            category=category,
            identity=identity,
            redirect_chain=list(signals.redirect_chain),
            evidence=evidence,
            uncertainty=uncertainty,
        )

    # 1. The browser itself failed; nothing about the page is trustworthy.
    if signals.browser_error:
        return result(
            PageReadiness.BROWSER_ERROR,
            f"Browser could not load the page: {signals.browser_error}",
            0.95,
            category="browser_error",
        )
    if not signals.observed_url or signals.observed_url.strip() in ("about:blank", ""):
        return result(
            PageReadiness.BROWSER_ERROR,
            "Browser stayed on a blank page instead of loading the target URL",
            0.9,
            category="browser_error",
        )

    # 2. Transport / gateway failures are infrastructure, not application defects.
    status = signals.http_status
    if status in (502, 503, 504):
        return result(
            PageReadiness.PROXY_OR_GATEWAY_ERROR,
            f"The host returned HTTP {status}; the application behind the proxy was unreachable",
            0.92,
            category="proxy_error",
        )
    if status == 500:
        return result(
            PageReadiness.APPLICATION_ERROR,
            "The application returned HTTP 500",
            0.85,
            category="application_error",
        )

    # 3. Silently following a redirect to another deployment is never allowed.
    if not integrity.aligned:
        return result(
            PageReadiness.UNKNOWN_PAGE,
            integrity.reason,
            0.9,
            category="unexpected_redirect",
            uncertainty=(
                f"Requested {integrity.requested_host} but the browser observed {integrity.observed_host}"
            ),
        )

    # 4. Authentication is a legitimate application state.
    if _looks_like_auth(signals, auth_kind):
        return result(
            PageReadiness.AUTHENTICATION_REQUIRED,
            "The application is presenting an authentication barrier",
            0.9,
            category="auth_required",
            identity=identity_token,
        )

    # 5. Explicit denial.
    if _looks_like_access_denied(signals, text):
        return result(
            PageReadiness.ACCESS_DENIED,
            "The host refused access (401/403 or an access-denied page)",
            0.88,
            category="access_denied",
        )

    # 6. Provider interstitial. Branding alone is not enough; structure must agree.
    interstitial, interstitial_reason = _looks_like_hosting_interstitial(
        signals, text, title
    )
    if interstitial and not identity_matched:
        return result(
            PageReadiness.HOSTING_INTERSTITIAL,
            interstitial_reason,
            0.86,
            category="hosting_unavailable",
            uncertainty="The page carries hosting-provider branding and no application identity",
        )

    # 7. Ordering matters: a loading page is retryable, an app error is terminal.
    if _looks_like_loading(signals, text, title) and not identity_matched:
        uncertainty = None
        if previous and previous.state is PageReadiness.APPLICATION_LOADING:
            uncertainty = (
                "The page still looks like a loading state after re-observation"
            )
        return result(
            PageReadiness.APPLICATION_LOADING,
            "The page contains only loading indicators and no application structure yet",
            0.72,
            category="unresolved_loading",
            uncertainty=uncertainty,
        )

    if _looks_like_app_error(signals, text, title):
        return result(
            PageReadiness.APPLICATION_ERROR,
            "The page displays an application or infrastructure error",
            0.8,
            category="application_error",
        )

    # 8. Positive readiness requires corroborating structure, not just a title.
    score, score_reasons = _readiness_score(signals, identity_matched)
    informative_title = title not in _GENERIC_TITLES
    if (
        score >= 2
        and identity_matched
        and signals.text_length > 0
    ) or (
        score >= 3
        and (informative_title or identity_matched)
        and signals.text_length > 0
    ):
        return result(
            PageReadiness.APPLICATION_READY,
            "Page shows application identity plus navigation and controls ("
            + ", ".join(score_reasons)
            + ")",
            min(0.95, 0.7 + 0.06 * score),
            identity=identity_token,
        )

    if score >= 2 and identity_matched and signals.interactive_count >= 2:
        return result(
            PageReadiness.APPLICATION_READY,
            "Page shows application identity and controls",
            0.7,
            identity=identity_token,
        )

    return result(
        PageReadiness.UNKNOWN_PAGE,
        "Page could not be identified as the requested application",
        0.5,
        category="unknown_page",
        uncertainty="No matching identity, navigation or application structure was observed",
        identity=identity_token,
    )


class ReadinessWaiter:
    """Re-observe the page a bounded number of times until it becomes usable.

    Only retryable states (loading / hosting interstitial) are retried. Every
    probe result is returned so callers can record the full observation history.
    """

    def __init__(
        self,
        probe: Callable[[], Awaitable[ReadinessAssessment]],
        *,
        intervals: Sequence[float] = (0.5, 1.0, 2.0, 3.0),
        total_timeout: float = 20.0,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._probe = probe
        self._intervals = tuple(max(0.0, float(i)) for i in intervals)
        self._total_timeout = max(0.0, float(total_timeout))
        self._sleep = sleep
        self._clock = clock

    @staticmethod
    def _fingerprint(assessment: ReadinessAssessment) -> str:
        digest = hashlib.sha256()
        digest.update((assessment.observed_url or "").encode("utf-8", "ignore"))
        digest.update(b"|")
        digest.update(
            " ".join(assessment.evidence.get("title", [])).encode("utf-8", "ignore")
        )
        digest.update(b"|")
        digest.update(
            " ".join(assessment.evidence.get("structure", [])).encode("utf-8", "ignore")
        )
        return digest.hexdigest()

    async def resolve(
        self,
        initial: ReadinessAssessment,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> ReadinessAssessment:
        current = initial
        if not current.retryable or not self._intervals:
            return current

        started = self._clock()
        for interval in self._intervals:
            if is_cancelled and is_cancelled():
                return current
            if self._clock() - started >= self._total_timeout:
                break
            await self._sleep(interval)
            if is_cancelled and is_cancelled():
                return current
            if self._clock() - started >= self._total_timeout:
                break
            previous_fingerprint = self._fingerprint(current)
            current = await self._probe()
            if not current.retryable:
                return current
            if self._fingerprint(current) == previous_fingerprint:
                current.uncertainty = (
                    current.uncertainty
                    or "The page did not change between readiness checks"
                )
        return current
