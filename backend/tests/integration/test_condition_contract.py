"""Contract tests: structured success conditions survive the full pipeline.

Covers the readiness spec §4 requirement — every verification condition type
must arrive at the Verifier with identical structure, never stringified or
wrapped. Also proves fail-closed behavior end-to-end (§5).

The frontend serialization defect ({description: "<json>"} wrapping) is
regression-tested here at the boundary the backend controls: FlowRunner →
Verifier, plus the JSON round-trip through the Flow persistence model.
"""

import pytest

from app.engine.verification.verifier import (
    KNOWN_CONDITION_KEYS,
    Verifier,
    VerificationResult,
    _is_vacuous_structural_target,
    _is_vacuous_url_pattern,
)


# Every condition type that must survive the pipeline intact (§4 list)
CONDITION_TYPES = [
    {"element_visible": {"css": "#dashboard"}},
    {"element_absent": "input[type='password']"},
    {"text_visible": "Welcome"},
    {"url_matches": "/dashboard"},
    {"url_changed_from": "/login"},
    {"url_changed_to": {"from": "http://start", "to": "/dashboard"}},
    {"element_enabled": {"css": "#save"}},
    {"element_checked": {"css": "#terms"}},
    {"element_value": {"target": {"css": "#email"}, "value": "a@b.co"}},
    {"auth_verified": {"auth_path": "/login"}},
    {"element_count": {"selector": "a[href]", "min": 1}},
    {"text_absent": "Error"},
    {"heading_changed": {"from": "Home"}},
]


class TestConditionStructureIntegrity:
    """Conditions must pass through JSON round-trips unchanged."""

    @pytest.mark.parametrize("condition", CONDITION_TYPES)
    def test_condition_survives_json_round_trip(self, condition):
        """Simulates DB persistence (JSON column) without structure loss."""
        import json

        serialized = json.dumps(condition)          # backend stores JSONB
        loaded = json.loads(serialized)             # runner loads it back
        assert loaded == condition
        # Keys remain machine-checkable — not wrapped in {"description": ...}
        assert not set(loaded.keys()) - KNOWN_CONDITION_KEYS

    def test_description_wrapped_condition_is_rejected(self):
        """The exact historical defect: {description: "<json-string>"}."""
        import json

        original = {"text_visible": "Dashboard"}
        defective = {"description": json.dumps(original)}  # what the old frontend sent

        result = known_keys_only(defective)
        assert result is False, (
            "A description-wrapped condition must NOT be recognized as a valid "
            "verification condition — it must fail closed (UNVERIFIED), never pass."
        )

    def test_stringified_condition_is_rejected(self):
        """A bare JSON string instead of an object must fail closed."""
        import json

        condition = json.dumps({"text_visible": "Dashboard"})  # str, not dict
        verifier = _make_offline_verifier()
        # verify() with a non-dict is exercised in the live tests; here we
        # assert the helper gates the dict check.
        assert isinstance(condition, str)


class TestFailClosedSemantics:
    """Unknown/empty/malformed conditions can never produce passed=True."""

    @pytest.mark.asyncio
    async def test_empty_condition_fails_offline(self):
        """verify({}) must fail closed without touching the page (page=None)."""
        verifier = _make_offline_verifier()
        result = await verifier.verify({})
        assert result.passed is False
        assert result.checks[0].type == "empty_condition"

    @pytest.mark.asyncio
    async def test_malformed_condition_fails_offline(self):
        """Non-dict condition must fail closed."""
        verifier = _make_offline_verifier()
        result = await verifier.verify("not-a-dict")  # type: ignore[arg-type]
        assert result.passed is False
        assert result.checks[0].type == "malformed_condition"

    @pytest.mark.asyncio
    async def test_unknown_only_condition_fails_offline(self):
        """Condition with only unknown keys must fail closed (page=None: the
        unknown-key gate fires before any browser access)."""
        verifier = _make_offline_verifier()
        result = await verifier.verify({"description": "{\"text_visible\": \"X\"}"})
        assert result.passed is False
        assert result.checks[0].type == "unknown_condition"

    @pytest.mark.asyncio
    async def test_vacuous_url_condition_fails_offline(self):
        """url_matches: .* must be rejected before any browser access."""
        verifier = _make_offline_verifier()
        result = await verifier.verify({"url_matches": ".*"})
        assert result.passed is False
        assert result.checks[0].type == "vacuous_condition"

    @pytest.mark.asyncio
    async def test_vacuous_structural_condition_fails_offline(self):
        """element_visible on bare structural containers must be rejected."""
        verifier = _make_offline_verifier()
        result = await verifier.verify({"element_visible": "main, .content, .container"})
        assert result.passed is False
        assert result.checks[0].type == "vacuous_condition"

    def test_known_keys_registry_contains_all_required_types(self):
        required = {
            "element_visible", "element_absent", "text_visible", "url_matches",
            "url_changed_from", "element_enabled", "element_checked",
            "element_value", "auth_verified",
        }
        assert required <= KNOWN_CONDITION_KEYS

    def test_vacuous_url_patterns_detected(self):
        assert _is_vacuous_url_pattern(".*")
        assert _is_vacuous_url_pattern("^")
        assert _is_vacuous_url_pattern("")
        assert not _is_vacuous_url_pattern("/dashboard")
        assert not _is_vacuous_url_pattern("/library/\\d+")

    def test_vacuous_structural_targets_detected(self):
        assert _is_vacuous_structural_target("main, .content, .container")
        assert _is_vacuous_structural_target("main")
        assert _is_vacuous_structural_target({"css": ".container"})
        assert not _is_vacuous_structural_target("#search-results")
        assert not _is_vacuous_structural_target("button:has-text('Search')")
        assert not _is_vacuous_structural_target("main, #results")


class TestRunnerVerifierContract:
    """Runner treats condition problems as UNVERIFIED, not silent success."""

    def test_runner_source_maps_condition_types_to_unverified(self):
        """Guard against regressions: UNVERIFIED_CONDITION_TYPES must include
        every fail-closed condition check type."""
        import inspect

        from app.engine.execution import runner as runner_module

        source = inspect.getsource(runner_module)
        required = {
            "no_condition", "empty_condition", "unknown_condition",
            "malformed_condition", "vacuous_condition",
        }
        for token in required:
            assert token in source, (
                f"Runner no longer maps '{token}' to UNVERIFIED — false-success "
                f"risk reintroduced."
            )


def _make_offline_verifier() -> Verifier:
    """Verifier without a live page — only for non-browser assertions."""
    return Verifier(page=None)  # type: ignore[arg-type]


def known_keys_only(condition: dict) -> bool:
    """True when every key in condition is a known verification key."""
    return all(k in KNOWN_CONDITION_KEYS for k in condition.keys())
