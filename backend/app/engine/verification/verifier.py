"""Deterministic verification engine.

Checks browser state against expected conditions.
Never assumes — always explicitly verifies.

Verification types:
- element_visible: Check if an element matching target is visible
- element_absent: Check if an element is NOT present (for post-login checks)
- element_count: Check element count {"selector": str, "min": int, "max": int}
- text_visible: Check if text content is visible on page
- text_absent: Check if text content is NOT visible on page
- heading_changed: Check if H1/H2 text changed from a prior snapshot (state-aware)
- url_matches: Check if current URL matches expected pattern
- url_changed_from: Check if URL changed AWAY from a pattern (for auth)
- url_changed_to: Check if URL changed TO a pattern relative to a start URL
- element_enabled / element_checked: element state checks
- element_value: input value check {"target": ..., "value": ...}
- page_loaded: Check if page is loaded (weak — prefer specific checks)
- auth_verified: Composite check for authentication success

FAIL-CLOSED SEMANTICS:
The verifier NEVER treats an unknown, empty, or malformed condition as success.
Unrecognized keys produce a failed `unknown_condition` check. A condition dict
whose keys are all unrecognized produces no pass — the execution must be
treated as UNVERIFIED by the runner.

VACUOUS-CONDITION REJECTION:
Some conditions are technically parseable but cannot prove a user outcome.
The verifier rejects:
- url_matches with pattern ".*" or "^" (matches every URL)
- element_visible against bare structural containers ("main", ".content",
  ".container", ".content, .container" etc.) when used as the ONLY check
"""

import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page

from app.engine.browser.resolver import TargetNotFoundError, TargetResolver

logger = logging.getLogger(__name__)

# Known verification condition keys (everything else is unknown → fail-closed)
KNOWN_CONDITION_KEYS = frozenset({
    "element_visible",
    "element_present",  # legacy alias
    "element_absent",
    "element_count",
    "text_visible",
    "text_present",     # legacy alias
    "text_absent",
    "heading_changed",
    "url_matches",
    "url_changed_from",
    "url_changed_to",
    "element_enabled",
    "element_checked",
    "element_value",
    "page_loaded",
    "auth_verified",
    "record_persisted",
    "search_results",
    "validation_error",
    "app_error_absent",
    "app_error_present",
})

# Structural containers that are valid diagnostics but cannot, alone, prove a
# user outcome (§16 of the readiness spec: INVALID AS SUCCESS PROOF).
_STRUCTURAL_CONTAINERS = frozenset({"main", "content", "container", "page", "body", "app", "root", "wrapper"})


def _normalize_url_for_matching(u: str) -> str:
    """Normalize a URL or URL pattern for resilient matching.

    Strips trailing slashes, drops 'www.' prefix, drops scheme (http://, https://),
    and standard default ports (:80, :443) so that e.g.:
    - 'https://summastudy.com.ng' matches 'https://www.summastudy.com.ng/'
    - 'http://example.com:80/dash/' matches 'https://example.com/dash'
    """
    if not u or not isinstance(u, str):
        return ""
    u_str = u.strip()
    try:
        # If no scheme present but it contains a dot before any slash, parse with //
        if "://" not in u_str and not u_str.startswith("/"):
            slash_idx = u_str.find("/")
            domain_part = u_str[:slash_idx] if slash_idx != -1 else u_str
            if "." in domain_part:
                u_str = "//" + u_str

        parsed = urlparse(u_str)
        if parsed.netloc:
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            if netloc.endswith(":80") or netloc.endswith(":443"):
                netloc = netloc.rsplit(":", 1)[0]
            path = parsed.path.rstrip("/")
            query = f"?{parsed.query}" if parsed.query else ""
            return f"{netloc}{path}{query}"
        return u_str.rstrip("/")
    except Exception:
        return u_str.rstrip("/")


def _is_vacuous_url_pattern(pattern: str) -> bool:
    """True when a url_matches pattern matches every possible URL."""
    p = (pattern or "").strip()
    return p in (".*", "^", "^$", "", "*", ".*") or p == r".*"


def _is_vacuous_structural_target(target: Any) -> bool:
    """True when a target is purely a structural container selector.

    Accepts the dict or string form. 'main, .content, .container' and friends
    are diagnostics, not outcome proofs.
    """
    if isinstance(target, dict):
        target = target.get("css") or target.get("text") or ""
    if not isinstance(target, str):
        return False
    parts = [p.strip().lower() for p in target.split(",") if p.strip()]
    if not parts:
        return False
    for part in parts:
        # strip css sugar: 'main', '.content', '#container', 'div.container'
        token = part.lstrip(".#")
        # drop element prefixes like 'div.' / 'section.'
        if "." in token:
            token = token.split(".")[-1]
        if token not in _STRUCTURAL_CONTAINERS:
            return False
    return True


def _contains_as_word(content_lower: str, value: str) -> bool:
    """Whole-word (case-insensitive) containment for verification snippets.

    Plain substring matching creates fail-positive proof: value "2" would
    match "222" or "label=2"; "er" would match "Footer". Only bounded
    occurrences count as evidence.
    """
    v = (value or "").strip().lower()
    if not v:
        return False
    pattern = r"(?:^|[^a-z0-9_])" + re.escape(v) + r"(?:$|[^a-z0-9_])"
    return re.search(pattern, content_lower) is not None


def is_vacuous_condition(condition: Any) -> bool:
    """True when a condition cannot prove a user outcome (empty, unknown, or vacuous)."""
    if not isinstance(condition, dict) or not condition:
        return True

    # Unknown condition keys fail-closed
    unknown_keys = [k for k in condition.keys() if k not in KNOWN_CONDITION_KEYS]
    if unknown_keys:
        return True

    has_non_vacuous = False
    for k, v in condition.items():
        if k == "url_matches":
            if isinstance(v, str) and not _is_vacuous_url_pattern(v):
                has_non_vacuous = True
        elif k in ("element_visible", "element_present"):
            if not _is_vacuous_structural_target(v):
                has_non_vacuous = True
        elif k == "page_loaded":
            pass
        elif k == "record_persisted":
            if isinstance(v, str):
                if v.strip():
                    has_non_vacuous = True
            elif isinstance(v, dict):
                fields = v.get("expected_fields") or {}
                texts = v.get("expected_text")
                if isinstance(texts, str):
                    texts = [texts]
                has_values = isinstance(fields, dict) and any(str(val).strip() for val in fields.values())
                has_texts = isinstance(texts, (list, tuple)) and any(str(t).strip() for t in texts)
                if has_values or has_texts:
                    has_non_vacuous = True
        elif k == "search_results":
            if isinstance(v, dict):
                expected = v.get("expected_matches")
                excluded = v.get("excluded_matches")
                if isinstance(expected, str):
                    expected = [expected]
                if isinstance(excluded, str):
                    excluded = [excluded]
                has_expected = isinstance(expected, (list, tuple)) and any(str(i).strip() for i in expected)
                has_excluded = isinstance(excluded, (list, tuple)) and any(str(i).strip() for i in excluded)
                if has_expected or has_excluded:
                    has_non_vacuous = True
        elif k == "validation_error":
            if isinstance(v, str):
                if v.strip():
                    has_non_vacuous = True
            elif isinstance(v, dict):
                if any(str(v.get(key) or "").strip() for key in ("message", "field", "selector")):
                    has_non_vacuous = True
        else:
            has_non_vacuous = True

    return not has_non_vacuous


def _heuristic_compile_expectation(
    objective: str,
    expected_outcome: str,
    page_context: dict | None = None,
) -> dict:
    """Deterministic heuristic fallback when AI provider is unavailable."""
    text = f"{objective} {expected_outcome}".strip()
    if not text:
        return {}

    # Check if a specific URL path was explicitly mentioned (e.g. /dashboard or /explore)
    explicit_paths = re.findall(r"(?:^|\s)(/[\w\-/]+)", text)
    if explicit_paths:
        target_path = explicit_paths[0].rstrip("/")
        # Only use if explicitly qualified or present in page_context
        if target_path and target_path not in ("/account", "/profile") or (page_context and target_path in str(page_context)):
            return {"url_matches": target_path}

    # Quoted text is an exact string expectation
    quoted = re.findall(r"['\"]([^'\"]{3,50})['\"]", text)
    if quoted:
        return {"text_visible": quoted[0]}

    # "shows/displays/sees <text>" pattern
    shows_match = re.search(
        r"(?:sees|shows|displays|contains|shows text)\s+([A-Za-z0-9_\- ]{3,30})",
        text,
        re.I,
    )
    if shows_match:
        cand = shows_match.group(1).strip()
        if cand.lower() not in _STRUCTURAL_CONTAINERS:
            return {"text_visible": cand}

    # Keyword patterns for common intents (prefer text visibility over ungrounded paths)
    if any(k in text.lower() for k in ["account page", "account dashboard", "profile page", "logged in", "logged-in"]):
        return {"text_visible": "Account"}
    if "explore" in text.lower():
        return {"text_visible": "Explore"}
    if "dashboard" in text.lower():
        return {"text_visible": "Dashboard"}
    if "settings" in text.lower():
        return {"text_visible": "Settings"}
    if "quiz" in text.lower():
        return {"text_visible": "Quiz"}
    if "study" in text.lower():
        return {"text_visible": "Study"}

    page_match = re.search(r"\b([A-Z][a-z]{2,20})\s+page\b", text)
    if page_match:
        cand = page_match.group(1).strip()
        if cand.lower() not in _STRUCTURAL_CONTAINERS:
            return {"text_visible": cand}

    return {}


_DEFAULT_PROVIDER = object()


async def compile_expectation(
    objective: str,
    expected_outcome: str,
    provider: Any = _DEFAULT_PROVIDER,
    page_context: dict | None = None,
) -> dict:
    """Compile natural-language expectation/objective into a deterministic verification condition.

    Uses the AI provider with schema-validated output (CompiledExpectation).
    Runs the result through the verifier's vacuous-condition rejection.
    If it cannot compile a non-vacuous condition, returns a vacuous condition
    so the runner/verifier marks the execution UNVERIFIED, never PASSED.
    """
    if provider is _DEFAULT_PROVIDER:
        try:
            from app.engine.ai.provider import get_ai_provider
            provider = get_ai_provider()
        except Exception:
            provider = None

    condition: dict = {}
    if provider is not None:
        import json
        from app.engine.ai.schemas import CompiledExpectation
        system = (
            "You compile software-testing objectives and expected outcomes into "
            "deterministic verification conditions.\n"
            "Return JSON matching: {\"condition\": {<check_key>: <spec>}, \"explanation\": \"...\"}\n"
            "Known check keys:\n"
            "- element_visible: {'css': '...'} or {'text': '...'}\n"
            "- text_visible: '...'\n"
            "- url_matches: '...'\n"
            "- element_absent: {'css': '...'} or {'text': '...'}\n"
            "- text_absent: '...'\n"
            "- heading_changed: true\n"
            "- url_changed_to: '...'\n"
            "- url_changed_from: '...'\n"
            "- auth_verified: true\n\n"
            "CRITICAL INTEGRITY RULES:\n"
            "1. NEVER hallucinate fictional CSS class names (such as 'h1.account-title', '.dashboard-header', '#profile') "
            "or imaginary URLs unless observed in the page context.\n"
            "2. When verifying display or content, prefer `text_visible` (e.g. 'Account', 'Welcome', 'Profile') "
            "or `element_visible: {'text': '...'}` over ungrounded CSS selectors.\n"
            "3. Do NOT return vacuous conditions like url_matches '.*' or "
            "element_visible on bare structural containers (main, body, container, .content)."
        )
        context_str = ""
        if page_context:
            context_str = f"\nObserved Page Context:\n{json.dumps(page_context, indent=1)}\n"

        prompt = (
            f"Objective: {objective}\n"
            f"Expected Outcome: {expected_outcome}\n"
            f"{context_str}\n"
            "Compile into a deterministic verification condition grounded in observed realities."
        )
        try:
            compiled = await provider.generate_structured(system, prompt, CompiledExpectation)
            condition = (
                compiled.condition
                if isinstance(compiled, CompiledExpectation)
                else (compiled.get("condition", {}) if isinstance(compiled, dict) else {})
            )
            # Filter condition strictly to known verification keys
            condition = {k: v for k, v in condition.items() if k in KNOWN_CONDITION_KEYS}
            # Guard against hallucinated specific CSS selectors like h1.account-title when not grounded
            if isinstance(condition.get("element_visible"), dict) and "css" in condition["element_visible"]:
                css_sel = condition["element_visible"]["css"]
                if "account-title" in css_sel or (not page_context and ("." in css_sel or "#" in css_sel)):
                    condition["text_visible"] = "Account" if "account" in css_sel.lower() else "Dashboard"
                    del condition["element_visible"]

            # Guard against hallucinated /account or /profile URL paths when unobserved
            url_match = condition.get("url_matches")
            if isinstance(url_match, str):
                normalized_path = url_match.rstrip("/").lower()
                if normalized_path in ("/account", "/profile", "/user/account", "/my-account") and not (
                    page_context and url_match in str(page_context)
                ):
                    del condition["url_matches"]
                    if any(
                        kw in f"{objective} {expected_outcome}".lower()
                        for kw in ["sign in", "login", "log in", "signup", "sign up", "account", "logged"]
                    ):
                        condition["auth_verified"] = {"auth_path": "/login"}
        except Exception as e:
            logger.warning("compile_expectation AI generation failed: %s", e)
            condition = {}

    if not condition:
        condition = _heuristic_compile_expectation(objective, expected_outcome, page_context=page_context)

    if is_vacuous_condition(condition):
        # Return a vacuous condition that the verifier rejects
        return {"url_matches": ".*"}

    return condition


@dataclass
class VerificationCheck:

    """Result of a single verification check."""

    type: str
    passed: bool
    expected: Any = None
    actual: Any = None
    message: str = ""
    evidence_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "type": self.type,
            "passed": self.passed,
        }
        if self.expected is not None:
            d["expected"] = self.expected
        if self.actual is not None:
            d["actual"] = self.actual
        if self.message:
            d["message"] = self.message
        if self.evidence_id:
            d["evidence_id"] = self.evidence_id
        if self.details:
            d["details"] = self.details
        return d


@dataclass
class VerificationResult:
    """Result of all verification checks."""

    passed: bool
    checks: list[VerificationCheck]
    evidence_ids: list[str] = field(default_factory=list)
    screenshot_bytes: bytes | None = None
    outcome: str | None = None

    def __post_init__(self):
        if self.outcome is None:
            if not self.checks:
                self.outcome = "UNVERIFIED"
            elif any(c.type in ("unknown_condition", "empty_condition", "malformed_condition") for c in self.checks):
                self.outcome = "UNVERIFIED"
            elif any(c.type == "auth_barrier" or "auth required" in (c.message or "").lower() for c in self.checks):
                self.outcome = "BLOCKED"
            elif self.passed:
                self.outcome = "PASSED"
            else:
                self.outcome = "FAILED"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "outcome": self.outcome,
            "checks": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.checks],
            "evidence_ids": self.evidence_ids,
        }


class VerificationError(Exception):
    """Raised when verification encounters an error."""

    def __init__(self, message: str, check_type: str = ""):
        self.check_type = check_type
        super().__init__(message)


class Verifier:
    """Deterministic browser state verifier.

    Checks browser state against expected conditions.
    Each check explicitly queries the browser — never assumes.

    Usage:
        verifier = Verifier(page)
        result = await verifier.verify({"element_visible": {"text": "Dashboard"}})
        if result.passed:
            print("Verification passed")
    """

    def __init__(self, page: Page):
        self.page = page
        self.resolver = TargetResolver(page)

    async def verify(self, condition: dict) -> VerificationResult:
        """Verify a condition against current browser state.

        FAIL-CLOSED: unknown keys, empty conditions, and malformed values
        produce failed checks — never a silent pass. See module docstring.

        Args:
            condition: Dict with one or more verification checks.

        Returns:
            VerificationResult with all check results.
        """
        checks: list[VerificationCheck] = []

        if not isinstance(condition, dict):
            return VerificationResult(
                passed=False,
                checks=[VerificationCheck(
                    type="malformed_condition",
                    passed=False,
                    expected="verification condition object",
                    actual=repr(condition)[:200],
                    message="Verification condition must be an object with known check keys",
                )],
            )

        if not condition:
            return VerificationResult(
                passed=False,
                checks=[VerificationCheck(
                    type="empty_condition",
                    passed=False,
                    message="No verification condition was provided — outcome cannot be proven",
                )],
            )

        # Fail-closed on unknown keys. This is the critical defense against
        # e.g. {"description": "..."} payloads being interpreted as success.
        unknown_keys = [k for k in condition.keys() if k not in KNOWN_CONDITION_KEYS]
        if unknown_keys:
            checks.append(VerificationCheck(
                type="unknown_condition",
                passed=False,
                expected="one of: " + ", ".join(sorted(KNOWN_CONDITION_KEYS)),
                actual=", ".join(unknown_keys),
                message=(
                    f"Unrecognized verification keys: {unknown_keys}. "
                    "Unknown conditions cannot be treated as success."
                ),
            ))
            return VerificationResult(passed=False, checks=checks)

        # Support both element_visible and element_present
        if "element_visible" in condition:
            check = await self._check_element_visible(condition["element_visible"])
            checks.append(check)
        elif "element_present" in condition:
            check = await self._check_element_visible(condition["element_present"])
            checks.append(check)

        # Support both text_visible and text_present
        if "text_visible" in condition:
            check = await self._check_text_visible(condition["text_visible"])
            checks.append(check)
        elif "text_present" in condition:
            check = await self._check_text_visible(condition["text_present"])
            checks.append(check)

        if "url_matches" in condition:
            check = await self._check_url_matches(condition["url_matches"])
            checks.append(check)

        if "element_enabled" in condition:
            check = await self._check_element_enabled(condition["element_enabled"])
            checks.append(check)

        if "element_checked" in condition:
            check = await self._check_element_checked(condition["element_checked"])
            checks.append(check)

        if "element_value" in condition:
            val_spec = condition["element_value"]
            if isinstance(val_spec, dict):
                target = val_spec.get("target")
                expected = val_spec.get("value", "")
            else:
                # Bare string form is ambiguous (target without expected value)
                # — fail-closed rather than guessing.
                target, expected = None, None
            if target is None or not isinstance(expected, str):
                checks.append(VerificationCheck(
                    type="element_value",
                    passed=False,
                    expected="{\"target\": <target>, \"value\": <string>}",
                    actual=repr(val_spec)[:100],
                    message="element_value requires a dict with 'target' and 'value'",
                ))
            else:
                check = await self._check_element_value(target, expected)
                checks.append(check)

        if "page_loaded" in condition:
            if len(condition) == 1:
                return VerificationResult(
                    passed=False,
                    outcome="UNVERIFIED",
                    checks=[VerificationCheck(
                        type="page_loaded",
                        passed=False,
                        expected="observable user outcome check",
                        actual=self.page.url if hasattr(self.page, "url") else "loaded",
                        message="Page loading alone cannot prove mission outcome — specific state assertion required",
                    )],
                )
            check = await self._check_page_loaded()
            checks.append(check)

        if "url_changed_from" in condition:
            check = await self._check_url_changed_from(condition["url_changed_from"])
            checks.append(check)

        if "url_changed_to" in condition:
            check = await self._check_url_changed_to(condition["url_changed_to"])
            checks.append(check)

        if "element_absent" in condition:
            check = await self._check_element_absent(condition["element_absent"])
            checks.append(check)

        if "element_count" in condition:
            check = await self._check_element_count(condition["element_count"])
            checks.append(check)

        if "text_absent" in condition:
            check = await self._check_text_absent(condition["text_absent"])
            checks.append(check)

        if "heading_changed" in condition:
            check = await self._check_heading_changed(condition["heading_changed"])
            checks.append(check)

        if "auth_verified" in condition:
            auth_checks = await self._check_auth_verified(condition["auth_verified"])
            checks.extend(auth_checks)

        if "record_persisted" in condition:
            check = await self._check_record_persisted(condition["record_persisted"])
            checks.append(check)

        if "search_results" in condition:
            check = await self._check_search_results(condition["search_results"])
            checks.append(check)

        if "validation_error" in condition:
            check = await self._check_validation_error(condition["validation_error"])
            checks.append(check)

        if "app_error_absent" in condition:
            check = await self._check_app_error_absent(condition["app_error_absent"])
            checks.append(check)

        if "app_error_present" in condition:
            check = await self._check_app_error_present(condition["app_error_present"])
            checks.append(check)

        # No known checks at all → fail-closed (unknown-only condition)
        if not checks:
            return VerificationResult(
                passed=False,
                checks=[VerificationCheck(
                    type="unknown_condition",
                    passed=False,
                    expected="at least one known verification check",
                    actual=sorted(condition.keys()),
                    message="Condition contained no known verification checks",
                )],
            )

        # Vacuous-success guard: a condition that only proves structural state
        # ("a page container is visible") or matches every URL cannot prove a
        # user outcome. Reject it explicitly rather than silently passing.
        if is_vacuous_condition(condition):
            return VerificationResult(
                passed=False,
                checks=[VerificationCheck(
                    type="vacuous_condition",
                    passed=False,
                    expected="a non-vacuous condition that discriminates the intended outcome",
                    actual=repr(condition)[:200],
                    message=(
                        f"Condition {condition} is vacuous or purely structural and cannot prove a user outcome"
                    ),
                )],
            )

        all_passed = all(c.passed for c in checks)
        return VerificationResult(passed=all_passed, checks=checks)

    async def _check_element_visible(self, target: dict) -> VerificationCheck:
        """Check if an element matching the target is visible.

        Args:
            target: Target specification (role, name, label, test_id, text, css).
        """
        try:
            # Try to resolve the target
            locator = await self._resolve_target(target)
            count = await locator.count()

            if count == 0:
                return VerificationCheck(
                    type="element_visible",
                    passed=False,
                    expected=target,
                    actual="not_found",
                    message="No matching element found",
                )

            if count > 1:
                return VerificationCheck(
                    type="element_visible",
                    passed=False,
                    expected=target,
                    actual=f"{count}_matches",
                    message=f"Ambiguous: {count} elements match",
                )

            # Check visibility
            visible = await locator.is_visible()
            return VerificationCheck(
                type="element_visible",
                passed=visible,
                expected=target,
                actual="visible" if visible else "hidden",
            )

        except Exception as e:
            return VerificationCheck(
                type="element_visible",
                passed=False,
                expected=target,
                actual="error",
                message=str(e),
            )

    async def _check_text_visible(self, text: str) -> VerificationCheck:
        """Check if text content is visible on the page.

        Args:
            text: Text to search for in visible content.
        """
        try:
            body = await self.page.query_selector("body")
            if not body:
                return VerificationCheck(
                    type="text_visible",
                    passed=False,
                    expected=text,
                    actual="no_body",
                    message="No body element found",
                )

            content = await body.inner_text()
            passed = text in content

            return VerificationCheck(
                type="text_visible",
                passed=passed,
                expected=text,
                actual=content[:200] if content else "",
            )

        except Exception as e:
            return VerificationCheck(
                type="text_visible",
                passed=False,
                expected=text,
                actual="error",
                message=str(e),
            )

    async def _check_url_matches(self, pattern: str) -> VerificationCheck:
        """Check if current URL matches expected pattern.

        Args:
            pattern: URL pattern to match. Supports:
                - Exact match: "http://example.com/dashboard"
                - Contains: "dashboard"
                - Regex: "/dashboard/\\d+"
        """
        try:
            current_url = self.page.url

            # 1. Try raw exact match
            if current_url == pattern:
                return VerificationCheck(
                    type="url_matches",
                    passed=True,
                    expected=pattern,
                    actual=current_url,
                )

            # 2. Try normalized exact match (handles www., trailing slash, protocol differences)
            norm_curr = _normalize_url_for_matching(current_url)
            norm_pat = _normalize_url_for_matching(pattern)
            if norm_curr and norm_pat and norm_curr == norm_pat:
                return VerificationCheck(
                    type="url_matches",
                    passed=True,
                    expected=pattern,
                    actual=current_url,
                )

            # 3. Try raw contains
            if pattern in current_url:
                return VerificationCheck(
                    type="url_matches",
                    passed=True,
                    expected=pattern,
                    actual=current_url,
                )

            # 4. Try normalized contains
            if norm_pat and norm_curr and norm_pat in norm_curr:
                return VerificationCheck(
                    type="url_matches",
                    passed=True,
                    expected=pattern,
                    actual=current_url,
                )

            # 5. Try regex on raw URL
            try:
                if re.search(pattern, current_url):
                    return VerificationCheck(
                        type="url_matches",
                        passed=True,
                        expected=pattern,
                        actual=current_url,
                    )
            except re.error:
                pass

            # 6. Try regex on normalized URL
            try:
                if norm_curr and re.search(pattern, norm_curr):
                    return VerificationCheck(
                        type="url_matches",
                        passed=True,
                        expected=pattern,
                        actual=current_url,
                    )
            except re.error:
                pass

            return VerificationCheck(
                type="url_matches",
                passed=False,
                expected=pattern,
                actual=current_url,
                message=f"Current URL '{current_url}' does not match pattern '{pattern}'",
            )

        except Exception as e:
            return VerificationCheck(
                type="url_matches",
                passed=False,
                expected=pattern,
                actual="error",
                message=str(e),
            )

    async def _check_element_enabled(self, target: Any) -> VerificationCheck:
        """Check if target element is enabled."""
        try:
            locator = await self._resolve_target(target)
            enabled = await locator.is_enabled()
            return VerificationCheck(
                type="element_enabled",
                passed=enabled,
                expected=target,
                actual="enabled" if enabled else "disabled",
            )
        except Exception as e:
            return VerificationCheck(
                type="element_enabled",
                passed=False,
                expected=target,
                actual="error",
                message=str(e),
            )

    async def _check_element_checked(self, target: Any) -> VerificationCheck:
        """Check if target checkbox or radio is checked."""
        try:
            locator = await self._resolve_target(target)
            checked = await locator.is_checked()
            return VerificationCheck(
                type="element_checked",
                passed=checked,
                expected=target,
                actual="checked" if checked else "unchecked",
            )
        except Exception as e:
            return VerificationCheck(
                type="element_checked",
                passed=False,
                expected=target,
                actual="error",
                message=str(e),
            )

    async def _check_element_value(self, target: Any, expected_value: str) -> VerificationCheck:
        """Check if target input element value equals expected value."""
        try:
            locator = await self._resolve_target(target)
            actual_val = await locator.input_value()
            passed = actual_val == expected_value
            return VerificationCheck(
                type="element_value",
                passed=passed,
                expected=expected_value,
                actual=actual_val,
            )
        except Exception as e:
            return VerificationCheck(
                type="element_value",
                passed=False,
                expected=expected_value,
                actual="error",
                message=str(e),
            )

    async def _check_page_loaded(self) -> VerificationCheck:
        """Check if the current page is loaded and usable.

        NOTE: This is a weak check. Prefer url_matches or element_visible for specific verification.
        """
        try:
            url = self.page.url
            if not url or url == "about:blank":
                return VerificationCheck(
                    type="page_loaded",
                    passed=False,
                    actual="blank",
                    message="Page is blank",
                )
            body = await self.page.query_selector("body")
            if not body:
                return VerificationCheck(
                    type="page_loaded",
                    passed=False,
                    actual="no_body",
                    message="No body found",
                )
            return VerificationCheck(
                type="page_loaded",
                passed=True,
                actual=url,
            )
        except Exception as e:
            return VerificationCheck(
                type="page_loaded",
                passed=False,
                actual="error",
                message=str(e),
            )

    async def _check_url_changed_to(self, config: dict | str) -> VerificationCheck:
        """Check if URL changed TO a pattern relative to a start URL.

        State-aware check: config = {"from": "<start_url>", "to": "<pattern>"}.
        Both conditions must hold for a pass.
        """
        if isinstance(config, str):
            config = {"to": config}
        start = config.get("from", "")
        target_pattern = config.get("to", "")
        try:
            current_url = self.page.url
            checks_ok = True
            if start and (current_url == start or (_normalize_url_for_matching(current_url) == _normalize_url_for_matching(start))):
                if not target_pattern:
                    try:
                        has_dialog_or_modal = await self.page.locator("[role='dialog'], [role='alertdialog'], .modal, form, [role='region']").count() > 0
                        if has_dialog_or_modal:
                            return VerificationCheck(
                                type="url_changed_to",
                                passed=True,
                                expected=f"URL change or in-page view transition from {start}",
                                actual=current_url,
                                message="In-page state transition or modal rendered successfully",
                            )
                    except Exception:
                        pass
                return VerificationCheck(
                    type="url_changed_to",
                    passed=False,
                    expected=f"URL other than {start}",
                    actual=current_url,
                    message="URL has not changed from the starting page",
                )
            if target_pattern:
                m = await self._check_url_matches(target_pattern)
                m.type = "url_changed_to"
                if not m.passed:
                    m.message = f"URL did not change to expected pattern: {m.actual}"
                return m
            return VerificationCheck(type="url_changed_to", passed=checks_ok, actual=current_url)
        except Exception as e:
            return VerificationCheck(type="url_changed_to", passed=False, actual="error", message=str(e))

    async def _check_element_count(self, config: dict) -> VerificationCheck:
        """Check the number of elements matching a selector against min/max bounds.

        config: {"selector": str, "min": int (default 1), "max": int (optional)}
        Used to prove e.g. "at least one search result exists".
        """
        selector = config.get("selector", "") if isinstance(config, dict) else str(config)
        if not selector:
            return VerificationCheck(
                type="element_count", passed=False, actual="error",
                message="element_count requires a 'selector'",
            )
        try:
            min_count = int(config.get("min", 1)) if isinstance(config, dict) else 1
            max_count = int(config["max"]) if isinstance(config, dict) and config.get("max") is not None else None
            locator = self.page.locator(selector)
            count = await locator.count()
            passed = count >= min_count and (max_count is None or count <= max_count)
            return VerificationCheck(
                type="element_count",
                passed=passed,
                expected=f">={min_count}" + (f" and <={max_count}" if max_count is not None else ""),
                actual=count,
                message=f"Found {count} matching elements" + ("" if passed else f" (required >= {min_count})"),
            )
        except Exception as e:
            return VerificationCheck(type="element_count", passed=False, actual="error", message=str(e))

    async def _check_text_absent(self, text: str) -> VerificationCheck:
        """Check that text is NOT visible on the page (e.g. error banners)."""
        try:
            body = await self.page.query_selector("body")
            if not body:
                return VerificationCheck(type="text_absent", passed=False, expected=f"absent: {text}", actual="no_body")
            content = await body.inner_text()
            present = text in content
            return VerificationCheck(
                type="text_absent",
                passed=not present,
                expected=f"not visible: {text}",
                actual="visible" if present else "absent",
            )
        except Exception as e:
            return VerificationCheck(type="text_absent", passed=False, actual="error", message=str(e))

    async def _check_heading_changed(self, config: dict | str) -> VerificationCheck:
        """Check that the page's primary heading differs from a prior value.

        State-aware check for resource/detail navigation:
        config: {"from": "<initial heading text>"} or plain string.
        Passes when H1/H2 differs from `from` (and is non-empty).
        """
        try:
            if isinstance(config, str):
                config = {"from": config}
            previous = (config.get("from") or "").strip()
            h1 = await self.page.query_selector("h1") or await self.page.query_selector("h2")
            current_heading = (await h1.inner_text()).strip() if h1 else ""
            if not current_heading:
                return VerificationCheck(
                    type="heading_changed", passed=False,
                    expected="a visible heading", actual="none",
                    message="No H1/H2 heading found on the page",
                )
            if previous and current_heading == previous:
                return VerificationCheck(
                    type="heading_changed", passed=False,
                    expected=f"heading other than '{previous}'",
                    actual=current_heading,
                    message="Heading did not change after the action",
                )
            return VerificationCheck(
                type="heading_changed", passed=True,
                expected=f"heading other than '{previous}'" if previous else "a visible heading",
                actual=current_heading,
            )
        except Exception as e:
            return VerificationCheck(type="heading_changed", passed=False, actual="error", message=str(e))

    async def _check_url_changed_from(self, pattern: str) -> VerificationCheck:
        """Check if URL changed AWAY from a pattern.

        Used for login verification: URL should no longer contain /login, /signin, etc.
        """
        try:
            current_url = self.page.url
            # URL should NOT contain the pattern
            norm_curr = _normalize_url_for_matching(current_url)
            norm_pat = _normalize_url_for_matching(pattern)
            still_on_auth = (pattern in current_url) or (bool(norm_pat) and norm_pat in norm_curr)
            return VerificationCheck(
                type="url_changed_from",
                passed=not still_on_auth,
                expected=f"not containing '{pattern}'",
                actual=current_url,
                message=f"Still on auth page: {current_url}" if still_on_auth else f"Navigated away from {pattern}",
            )
        except Exception as e:
            return VerificationCheck(
                type="url_changed_from",
                passed=False,
                expected=f"not containing '{pattern}'",
                actual="error",
                message=str(e),
            )

    async def _check_element_absent(self, target: Any) -> VerificationCheck:
        """Check if an element is NOT present or visible.

        Used for post-login checks: password field should be absent after login.
        """
        try:
            locator = await self._resolve_target(target)
            if inspect.isawaitable(locator):
                locator = await locator
            count = locator.count() if hasattr(locator, "count") else 0
            if inspect.isawaitable(count):
                count = await count
            # Element should have 0 matches (absent)
            passed = count == 0
            return VerificationCheck(
                type="element_absent",
                passed=passed,
                expected="absent",
                actual=f"found_{count}" if count > 0 else "absent",
                message=f"Element still present ({count} matches)" if count > 0 else "Element correctly absent",
            )
        except TargetNotFoundError:
            # Resolver explicitly determined the element does not exist — absence proven
            return VerificationCheck(
                type="element_absent",
                passed=True,
                expected="absent",
                actual="not_found",
            )
        except Exception:
            # Ambiguous failure (bad selector syntax, page error, etc.) must NOT
            # be treated as proof of absence — fail closed.
            return VerificationCheck(
                type="element_absent",
                passed=False,
                expected="absent",
                actual="error",
                message="Could not determine element absence — check failed (fail-closed)",
            )

    async def _check_auth_verified(self, config: dict | bool) -> list[VerificationCheck]:
        """Composite authentication verification.

        Multi-signal verification that replaces naive heuristics:
        1. URL changed away from auth path (if specified)
        2. Password field is absent from the DOM
        3. No authentication failure or error banners (e.g. 'invalid credentials', 'unauthorized')
        4. Positive session evidence:
           - User-provided post-login indicator, OR
           - Positive session indicators (logout button/link, user profile greeting, user menu)
        """
        if isinstance(config, bool):
            config = {}
        checks = []
        auth_path = config.get("auth_path", "/login")
        indicator = config.get("indicator")

        # Check 1: URL changed away from auth path
        url_check = await self._check_url_changed_from(auth_path)
        checks.append(url_check)

        # Check 2: Password field should be absent (we're no longer on login page)
        pwd_check = await self._check_element_absent("input[type='password']")
        checks.append(pwd_check)

        # Check 3: Check for visible auth failure messages in page
        body = await self.page.query_selector("body")
        body_text = (await self._safe_inner_text(body)).lower() if body else ""
        auth_error_patterns = [
            "invalid email or password",
            "invalid credentials",
            "incorrect password",
            "authentication failed",
            "unauthorized",
            "access denied",
            "please sign in to continue",
            "authentication required",
        ]
        detected_err = next((pat for pat in auth_error_patterns if pat in body_text), None)
        if detected_err:
            checks.append(VerificationCheck(
                type="auth_error_detected",
                passed=False,
                expected="successful authenticated session",
                actual=detected_err,
                message=f"Authentication error message detected in page: '{detected_err}'",
                details={"error": detected_err},
            ))

        # Check 4: Positive session evidence
        if indicator:
            if isinstance(indicator, str):
                text_check = await self._check_text_visible(indicator)
            else:
                text_check = await self._check_element_visible(indicator)
            checks.append(text_check)
        else:
            positive_signals = [
                "a[href*='logout']",
                "a[href*='signout']",
                "button:has-text('Log Out')",
                "button:has-text('Sign Out')",
                "button:has-text('Logout')",
                "#user-greeting",
                "#user-name",
                "[data-testid*='logout']",
                "[data-testid*='user-menu']",
                ".user-info",
            ]
            found_positive = False
            for sel in positive_signals:
                loc = await self._safe_loc(sel)
                count = await self._safe_count(loc)
                if count > 0 and await self._safe_is_visible(loc.first):
                    found_positive = True
                    checks.append(VerificationCheck(
                        type="auth_session_indicator",
                        passed=True,
                        expected="positive session indicator",
                        actual=sel,
                        message=f"Authenticated session indicator verified via '{sel}'",
                        details={"selector": sel},
                    ))
                    break

            if not found_positive:
                login_nav = await self._safe_loc("a[href*='login'], a[href*='signin'], button:has-text('Sign In')")
                login_count = await self._safe_count(login_nav)
                login_visible = False
                if login_count > 0:
                    for i in range(login_count):
                        if await self._safe_is_visible(login_nav.nth(i)):
                            login_visible = True
                            break
                if login_visible:
                    checks.append(VerificationCheck(
                        type="auth_session_indicator",
                        passed=False,
                        expected="authenticated session without login links",
                        actual="login_links_visible",
                        message="Login links are still visible and no session indicator (logout/profile) was observed",
                        details={"login_links_visible": True},
                    ))
                else:
                    # Absence of login links is NOT positive evidence of a
                    # session: a public page, a 404, or a blank page also has
                    # none. Authentication must be proven by an observable
                    # session control (logout/profile) or an explicit
                    # indicator. Fail closed instead of inferring success.
                    checks.append(VerificationCheck(
                        type="auth_session_indicator",
                        passed=False,
                        expected="positive session indicator (logout link, profile menu, or explicit indicator)",
                        actual="no_positive_session_evidence",
                        message=(
                            "No positive authenticated-session indicator was observed; "
                            "absence of login controls is not proof of authentication"
                        ),
                        details={"inferred": False},
                    ))

        return checks

    async def _check_record_persisted(self, config: dict | str) -> VerificationCheck:
        """Check that a created or updated record is persisted in the UI/data store.

        Supports cross-refresh verification via `reload=True`.
        config: {
            "selector": str | None,
            "expected_fields": dict[str, str] | None,
            "expected_text": str | list[str] | None,
            "reload": bool = False,
        }
        """
        if isinstance(config, str):
            config = {"expected_text": config}
        if not isinstance(config, dict):
            return VerificationCheck(
                type="record_persisted",
                passed=False,
                expected="dict with expected_fields or expected_text",
                actual=repr(config)[:100],
                message="record_persisted requires a specification dict or string",
            )

        should_reload = bool(config.get("reload", False))
        if should_reload:
            try:
                await self.page.reload(wait_until="domcontentloaded")
                await self.page.wait_for_timeout(300)
            except Exception as e:
                return VerificationCheck(
                    type="record_persisted",
                    passed=False,
                    expected="page reloaded and record persisted",
                    actual=f"reload_error: {e}",
                    message=f"Failed to reload page for persistence verification: {e}",
                )

        selector = config.get("selector")
        expected_fields = config.get("expected_fields") or {}
        expected_texts = config.get("expected_text")
        if isinstance(expected_texts, str):
            expected_texts = [expected_texts]
        elif expected_texts is None:
            expected_texts = []

        has_expected_values = (
            isinstance(expected_fields, dict)
            and any(str(v).strip() for v in expected_fields.values())
        ) or any(str(t).strip() for t in expected_texts if t is not None)
        if not has_expected_values:
            return VerificationCheck(
                type="record_persisted",
                passed=False,
                expected="at least one non-empty expected field or text",
                actual="no_expected_values",
                message=(
                    "record_persisted requires concrete expected field values or text; "
                    "an empty specification cannot prove persistence"
                ),
                details={"reloaded": should_reload, "selector": selector},
            )

        try:
            if selector:
                locator = self.page.locator(selector)
                count = await locator.count()
                if count == 0:
                    return VerificationCheck(
                        type="record_persisted",
                        passed=False,
                        expected=f"selector '{selector}' visible",
                        actual="not_found",
                        message=f"Target container for persisted record '{selector}' not found",
                        details={"reloaded": should_reload, "selector": selector},
                    )
                content = await locator.first.inner_text()
            else:
                body = await self.page.query_selector("body")
                content = (await body.inner_text()) if body else ""

            content_lower = content.lower()
            missing_fields = []
            for fname, fval in expected_fields.items():
                fv = str(fval).strip()
                if not fv or not _contains_as_word(content_lower, fv):
                    missing_fields.append(f"{fname}='{fval}'")

            missing_texts = []
            for t in expected_texts:
                tv = str(t).strip()
                if not tv or not _contains_as_word(content_lower, tv):
                    missing_texts.append(str(t))

            passed = len(missing_fields) == 0 and len(missing_texts) == 0
            details = {
                "reloaded": should_reload,
                "verified_fields": expected_fields,
                "verified_texts": expected_texts,
                "missing_fields": missing_fields,
                "missing_texts": missing_texts,
                "excerpt": content[:300].strip(),
            }

            if not passed:
                err_parts = []
                if missing_fields:
                    err_parts.append(f"missing fields: {', '.join(missing_fields)}")
                if missing_texts:
                    err_parts.append(f"missing text: {', '.join(missing_texts)}")
                msg = f"Record persistence check failed ({'; '.join(err_parts)})"
                if should_reload:
                    msg += " across browser reload"
                return VerificationCheck(
                    type="record_persisted",
                    passed=False,
                    expected=config,
                    actual={"missing_fields": missing_fields, "missing_texts": missing_texts},
                    message=msg,
                    details=details,
                )

            success_msg = "Record successfully verified as persisted"
            if should_reload:
                success_msg += " across browser reload"
            return VerificationCheck(
                type="record_persisted",
                passed=True,
                expected=config,
                actual="persisted",
                message=success_msg,
                details=details,
            )
        except Exception as e:
            return VerificationCheck(
                type="record_persisted",
                passed=False,
                expected=config,
                actual="error",
                message=f"Persistence check encountered error: {e}",
            )

    async def _safe_loc(self, selector: str) -> Any:
        loc = self.page.locator(selector)
        if inspect.isawaitable(loc):
            loc = await loc
        return loc

    async def _safe_count(self, loc: Any) -> int:
        if loc is None:
            return 0
        c = loc.count() if hasattr(loc, "count") else 0
        if inspect.isawaitable(c):
            c = await c
        return int(c)

    async def _safe_inner_text(self, el: Any) -> str:
        if el is None:
            return ""
        t = el.inner_text() if hasattr(el, "inner_text") else ""
        if inspect.isawaitable(t):
            t = await t
        return str(t or "")

    async def _safe_is_visible(self, el: Any) -> bool:
        if el is None:
            return False
        if inspect.isawaitable(el):
            el = await el
        v = el.is_visible() if hasattr(el, "is_visible") else False
        if inspect.isawaitable(v):
            v = await v
        return bool(v)

    async def _check_search_results(self, config: dict) -> VerificationCheck:
        """Check that search/filter results include expected items and exclude non-matching items.

        config: {
            "query": str,
            "expected_matches": list[str] | str,
            "excluded_matches": list[str] | str | None,
            "selector": str | None,
        }
        """
        if not isinstance(config, dict):
            return VerificationCheck(
                type="search_results",
                passed=False,
                expected="dict with query, expected_matches, excluded_matches",
                actual=repr(config)[:100],
                message="search_results requires a specification dict",
            )

        query = config.get("query", "")
        expected = config.get("expected_matches", [])
        if isinstance(expected, str):
            expected = [expected]
        excluded = config.get("excluded_matches", [])
        if isinstance(excluded, str):
            excluded = [excluded]
        elif excluded is None:
            excluded = []
        selector = config.get("selector")

        try:
            if selector:
                loc = await self._safe_loc(selector)
                count = await self._safe_count(loc)
                if count == 0:
                    return VerificationCheck(
                        type="search_results",
                        passed=False,
                        expected=f"results container matching '{selector}'",
                        actual="not_found",
                        message=f"Search results container '{selector}' not found",
                    )
                content = await self._safe_inner_text(loc.first)
            else:
                # Official container hierarchy: test-id'd results container
                # first, then structural table roles/classes, then body as the
                # last resort. Hardcoded app-specific ids are not portable.
                candidates = [
                    "[data-testid='results']",
                    "[role='table']",
                    "table",
                    "body",
                ]
                content = ""
                for cand in candidates:
                    loc = await self._safe_loc(cand)
                    count = await self._safe_count(loc)
                    if count > 0:
                        content = await self._safe_inner_text(loc.first)
                        break

            content_lower = content.lower()
            missing_expected = [
                item for item in expected
                if not _contains_as_word(content_lower, str(item).strip())
            ]
            unexpected_present = [
                item for item in excluded
                if _contains_as_word(content_lower, str(item).strip())
            ]

            passed = len(missing_expected) == 0 and len(unexpected_present) == 0
            details = {
                "query": query,
                "expected": expected,
                "excluded": excluded,
                "missing_expected": missing_expected,
                "unexpected_present": unexpected_present,
                "excerpt": content[:300].strip(),
            }

            if not passed:
                reasons = []
                if missing_expected:
                    reasons.append(f"did not find expected items: {missing_expected}")
                if unexpected_present:
                    reasons.append(f"incorrectly included excluded items: {unexpected_present}")
                return VerificationCheck(
                    type="search_results",
                    passed=False,
                    expected={"expected": expected, "excluded": excluded},
                    actual={"missing": missing_expected, "unexpected": unexpected_present},
                    message=f"Search verification failed for query '{query}': {'; '.join(reasons)}",
                    details=details,
                )

            return VerificationCheck(
                type="search_results",
                passed=True,
                expected={"expected": expected, "excluded": excluded},
                actual="results_match",
                message=f"Search results for query '{query}' verified: {len(expected)} matches found and {len(excluded)} non-matching records correctly excluded",
                details=details,
            )
        except Exception as e:
            return VerificationCheck(
                type="search_results",
                passed=False,
                expected=config,
                actual="error",
                message=f"Search verification error: {e}",
            )

    async def _check_validation_error(self, config: dict | str) -> VerificationCheck:
        """Check that a validation error message or error banner is visible.

        Validates expected validation rejections (negative test cases).
        config: {
            "message": str | None,
            "field": str | None,
            "selector": str | None,
        } or plain string message.
        """
        if isinstance(config, str):
            config = {"message": config}
        if not isinstance(config, dict):
            return VerificationCheck(
                type="validation_error",
                passed=False,
                expected="validation error specification",
                actual=repr(config)[:100],
                message="validation_error requires dict or string message",
            )

        expected_msg = (config.get("message") or "").strip().lower()
        field_name = config.get("field")
        selector = config.get("selector")

        try:
            # Check 1: Custom selector if provided
            if selector:
                loc = await self._safe_loc(selector)
                count = await self._safe_count(loc)
                if count > 0 and await self._safe_is_visible(loc.first):
                    text = await self._safe_inner_text(loc.first)
                    if not expected_msg or expected_msg in text.lower():
                        return VerificationCheck(
                            type="validation_error",
                            passed=True,
                            expected=config,
                            actual=text[:200].strip(),
                            message=f"Validation error observed: {text[:150].strip()}",
                            details={"text": text[:200].strip(), "selector": selector},
                        )

            # Check 2: Standard alert and error classes
            standard_selectors = [
                "[role='alert']",
                ".alert-danger",
                ".error-message",
                ".form-error",
                ".invalid-feedback",
                "#record-error",
                "#register-error",
                "#login-error",
            ]
            for sel in standard_selectors:
                loc = await self._safe_loc(sel)
                count = await self._safe_count(loc)
                for i in range(count):
                    el = loc.nth(i)
                    if await self._safe_is_visible(el):
                        text = (await self._safe_inner_text(el)).strip()
                        if not expected_msg or expected_msg in text.lower():
                            return VerificationCheck(
                                type="validation_error",
                                passed=True,
                                expected=config,
                                actual=text[:200],
                                message=f"Validation error observed: {text[:150]}",
                                details={"text": text[:200], "selector": sel},
                            )

            # Check 3: Field-specific aria-invalid or invalid state
            if field_name:
                field_loc = await self._safe_loc(f"[name='{field_name}'], #{field_name}")
                count = await self._safe_count(field_loc)
                if count > 0:
                    first_el = field_loc.first
                    get_attr = first_el.get_attribute("aria-invalid") if hasattr(first_el, "get_attribute") else None
                    if inspect.isawaitable(get_attr):
                        get_attr = await get_attr
                    # A decorated field alone does not prove the expected
                    # failure message: it proves the field was flagged
                    # invalid, not THIS validation path. Only treat it as
                    # proof when it also names the expected message.
                    if get_attr == "true" and expected_msg:
                        field_text = str(await self._safe_inner_text(first_el) or "").lower()
                        if expected_msg in field_text:
                            return VerificationCheck(
                                type="validation_error",
                                passed=True,
                                expected=config,
                                actual=field_text[:200],
                                message=f"Field {field_name} marked invalid with the expected message",
                                details={"field": field_name, "text": field_text[:200]},
                            )

            # Check 4: Text search if expected_msg provided
            if expected_msg:
                body = await self.page.query_selector("body")
                body_text = (await self._safe_inner_text(body)).lower() if body else ""
                if expected_msg in body_text:
                    return VerificationCheck(
                        type="validation_error",
                        passed=True,
                        expected=expected_msg,
                        actual="visible_in_body",
                        message=f"Validation error text '{expected_msg}' observed on page",
                        details={"message": expected_msg},
                    )

            return VerificationCheck(
                type="validation_error",
                passed=False,
                expected=config,
                actual="no_validation_error_found",
                message=f"Expected validation error '{expected_msg or field_name or selector}' was not observed",
            )
        except Exception as e:
            return VerificationCheck(
                type="validation_error",
                passed=False,
                expected=config,
                actual="error",
                message=f"Validation error check failed with exception: {e}",
            )

    async def _check_app_error_absent(self, config: Any = None) -> VerificationCheck:
        """Check that no unhandled application error, 500 error, or crash screen is visible."""
        try:
            error_locators = [
                "h1:has-text('500')",
                "h1:has-text('Internal Server Error')",
                "h1:has-text('Application Error')",
                "h1:has-text('Server Error')",
                "[role='alert']:has-text('Internal Server Error')",
                "[role='alert']:has-text('500')",
                ".error-page",
                "#error-page",
            ]
            for sel in error_locators:
                loc = await self._safe_loc(sel)
                count = await self._safe_count(loc)
                if count > 0 and await self._safe_is_visible(loc.first):
                    err_txt = (await self._safe_inner_text(loc.first)).strip()
                    return VerificationCheck(
                        type="app_error_absent",
                        passed=False,
                        expected="no application crash or 500 banner",
                        actual=err_txt[:200],
                        message=f"Application error screen or 500 banner detected: {err_txt[:100]}",
                    )
            return VerificationCheck(
                type="app_error_absent",
                passed=True,
                expected="no application crash or 500 banner",
                actual="clean",
                message="No application errors or 500 banners detected on page",
            )
        except Exception as e:
            return VerificationCheck(
                type="app_error_absent",
                passed=False,
                actual="error",
                message=f"Failed checking application error state: {e}",
            )

    async def _check_app_error_present(self, config: Any = None) -> VerificationCheck:
        """Check that an application error is present (for error boundary testing)."""
        res = await self._check_app_error_absent(config)
        return VerificationCheck(
            type="app_error_present",
            passed=not res.passed,
            expected="application error or 500 banner present",
            actual=res.actual,
            message="Application error correctly observed" if not res.passed else "Expected application error was not observed",
        )

    async def _resolve_target(self, target: Any):
        """Resolve a target specification to a Playwright Locator with resilient multi-strategy fallback.

        Accepts either dict specification or raw CSS/selector string.
        """
        from app.engine.browser.resolver import ResolutionStrategy

        if isinstance(target, str):
            target_str = target.strip()
            if (
                target_str.startswith("#")
                or target_str.startswith(".")
                or target_str.startswith("[")
                or "[" in target_str
                or ":" in target_str
                or ">" in target_str
                or "," in target_str
                or " " in target_str
                or target_str.startswith("input")
                or target_str.startswith("button")
                or target_str.startswith("a")
            ):
                loc = self.page.locator(target_str)
                if inspect.isawaitable(loc):
                    loc = await loc
                return loc.first
            try:
                return await self.resolver.resolve(target_str)
            except Exception:
                try:
                    return await self.resolver.resolve_first_visible(target_str)
                except Exception:
                    loc = self.page.locator(target_str)
                    if inspect.isawaitable(loc):
                        loc = await loc
                    return loc.first

        if not isinstance(target, dict):
            raise VerificationError("Invalid target specification", "resolve")

        # Text-only targets resolve directly through get_by_text so that
        # duplicate matches stay visible via count(). Resolver text
        # strategies return a single element and would hide ambiguity.
        if target.get("text") and not any(
            target.get(k) for k in ("role", "name", "label", "test_id", "css")
        ):
            get_by_text = getattr(self.page, "get_by_text", None)
            if get_by_text is not None:
                return get_by_text(str(target["text"]).strip())

        # Ranked candidate specifications from most specific to broadest
        candidates: list[tuple[str, dict[str, Any]]] = []
        if target.get("test_id"):
            candidates.append((target["test_id"], {"strategy": ResolutionStrategy.TEST_ID}))
        if target.get("role") and target.get("name"):
            candidates.append((target["name"], {"role": target["role"], "strategy": ResolutionStrategy.ROLE_NAME}))
        if target.get("label"):
            candidates.append((target["label"], {"strategy": ResolutionStrategy.LABEL}))
        if target.get("text"):
            candidates.append((target["text"], {"strategy": ResolutionStrategy.TEXT}))
        if target.get("name"):
            candidates.append((target["name"], {}))
        if target.get("css"):
            candidates.append((target["css"], {"strategy": ResolutionStrategy.CSS}))

        for target_val, kwargs in candidates:
            try:
                return await self.resolver.resolve(target_val, **kwargs)
            except Exception:
                continue

        for target_val, kwargs in candidates:
            try:
                return await self.resolver.resolve_first_visible(target_val, **kwargs)
            except Exception:
                continue

        if target.get("css"):
            return self.page.locator(target["css"]).first

        raise VerificationError(f"Target not found: {target}", "resolve")
