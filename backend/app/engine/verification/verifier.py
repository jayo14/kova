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

import logging
import re
from dataclasses import dataclass
from typing import Any

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
})

# Structural containers that are valid diagnostics but cannot, alone, prove a
# user outcome (§16 of the readiness spec: INVALID AS SUCCESS PROOF).
_STRUCTURAL_CONTAINERS = frozenset({"main", "content", "container", "page", "body", "app", "root", "wrapper"})


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
        else:
            has_non_vacuous = True

    return not has_non_vacuous


def _heuristic_compile_expectation(objective: str, expected_outcome: str) -> dict:
    """Deterministic heuristic fallback when AI provider is unavailable."""
    text = f"{objective} {expected_outcome}".strip()
    if not text:
        return {}
    url_match = re.search(
        r"/(?:dashboard|profile|settings|home|login|signup|account|welcome|orders|checkout)[\w\-]*",
        text,
        re.I,
    )
    if url_match:
        return {"url_matches": url_match.group(0)}
    quoted = re.findall(r"['\"]([^'\"]{3,50})['\"]", text)
    if quoted:
        return {"text_visible": quoted[0]}
    shows_match = re.search(
        r"(?:sees|shows|displays|contains|shows text)\s+([A-Za-z0-9_\- ]{3,30})",
        text,
        re.I,
    )
    if shows_match:
        cand = shows_match.group(1).strip()
        if cand.lower() not in _STRUCTURAL_CONTAINERS:
            return {"text_visible": cand}
    return {}


async def compile_expectation(
    objective: str,
    expected_outcome: str,
    provider: Any = None,
) -> dict:
    """Compile natural-language expectation/objective into a deterministic verification condition.

    Uses the AI provider with schema-validated output (CompiledExpectation).
    Runs the result through the verifier's vacuous-condition rejection.
    If it cannot compile a non-vacuous condition, returns a vacuous condition
    so the runner/verifier marks the execution UNVERIFIED, never PASSED.
    """
    if provider is None:
        try:
            from app.engine.ai.provider import get_ai_provider
            provider = get_ai_provider()
        except Exception:
            provider = None

    condition: dict = {}
    if provider is not None:
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
            "- auth_verified: true\n"
            "CRITICAL: Do NOT return vacuous conditions like url_matches '.*' or "
            "element_visible on bare structural containers (main, body, container, .content)."
        )
        prompt = (
            f"Objective: {objective}\n"
            f"Expected Outcome: {expected_outcome}\n\n"
            "Compile into a deterministic verification condition."
        )
        try:
            compiled = await provider.generate_structured(system, prompt, CompiledExpectation)
            condition = (
                compiled.condition
                if isinstance(compiled, CompiledExpectation)
                else (compiled.get("condition", {}) if isinstance(compiled, dict) else {})
            )
        except Exception as e:
            logger.warning("compile_expectation AI generation failed: %s", e)
            condition = {}

    if not condition:
        condition = _heuristic_compile_expectation(objective, expected_outcome)

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
        return d


@dataclass
class VerificationResult:
    """Result of all verification checks."""

    passed: bool
    checks: list[VerificationCheck]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
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

            # Try exact match first
            if current_url == pattern:
                return VerificationCheck(
                    type="url_matches",
                    passed=True,
                    expected=pattern,
                    actual=current_url,
                )

            # Try contains
            if pattern in current_url:
                return VerificationCheck(
                    type="url_matches",
                    passed=True,
                    expected=pattern,
                    actual=current_url,
                )

            # Try regex
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

            return VerificationCheck(
                type="url_matches",
                passed=False,
                expected=pattern,
                actual=current_url,
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
            if start and current_url == start:
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
            still_on_auth = pattern in current_url
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
            count = await locator.count()
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

    async def _check_auth_verified(self, config: dict) -> list[VerificationCheck]:
        """Composite authentication verification.

        Checks multiple signals to determine if authentication succeeded:
        1. URL changed away from auth path
        2. Password field is absent
        3. A post-login indicator is present (optional)

        Args:
            config: Dict with:
                - auth_path: The login/signup path to check URL changed from (e.g., "/login")
                - indicator: Optional text/element that should be visible after login
        """
        checks = []
        auth_path = config.get("auth_path", "/login")
        indicator = config.get("indicator")

        # Check 1: URL changed away from auth path
        url_check = await self._check_url_changed_from(auth_path)
        checks.append(url_check)

        # Check 2: Password field should be absent (we're no longer on login page)
        pwd_check = await self._check_element_absent("input[type='password']")
        checks.append(pwd_check)

        # Check 3: Optional post-login indicator
        if indicator:
            if isinstance(indicator, str):
                text_check = await self._check_text_visible(indicator)
            else:
                text_check = await self._check_element_visible(indicator)
            checks.append(text_check)

        return checks

    async def _resolve_target(self, target: Any):
        """Resolve a target specification to a Playwright Locator.

        Accepts either dict specification or raw CSS/selector string.
        """
        from app.engine.browser.resolver import ResolutionStrategy

        if isinstance(target, str):
            target_str = target.strip()
            if target_str.startswith("#") or target_str.startswith(".") or target_str.startswith("[") or "," in target_str:
                return self.page.locator(target_str).first
            try:
                return await self.resolver.resolve(target_str)
            except Exception:
                return self.page.locator(target_str).first

        if not isinstance(target, dict):
            raise VerificationError("Invalid target specification", "resolve")

        if "test_id" in target and target["test_id"]:
            return await self.resolver.resolve(
                target["test_id"], strategy=ResolutionStrategy.TEST_ID
            )
        if "role" in target and "name" in target and target["role"] and target["name"]:
            return await self.resolver.resolve(
                target["name"], role=target["role"], strategy=ResolutionStrategy.ROLE_NAME
            )
        if "label" in target and target["label"]:
            return await self.resolver.resolve(
                target["label"], strategy=ResolutionStrategy.LABEL
            )
        if "text" in target and target["text"]:
            return await self.resolver.resolve(
                target["text"], strategy=ResolutionStrategy.TEXT
            )
        if "css" in target and target["css"]:
            return self.page.locator(target["css"]).first
        if "name" in target and target["name"]:
            return await self.resolver.resolve(target["name"])

        raise VerificationError("Invalid target specification", "resolve")
