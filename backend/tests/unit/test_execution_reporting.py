from types import SimpleNamespace

from app.modules.executions.reporting import build_timeline, classify_failure, diagnose_failure, diagnose_verification, sanitize_payload, sanitize_text


def test_classifies_failure_without_collapsing_status_and_category():
    assert classify_failure("VERIFICATION_FAILED") == "application_behavior"
    assert classify_failure("AUTH_BLOCKED") == "authentication_or_authorization"
    assert classify_failure("BROWSER_START_FAILED") == "browser_infrastructure"
    assert diagnose_failure("NETWORK_ERROR", "Timed out at https://app.test/path?token=abc") == {
        "category": "network_or_application_server",
        "summary": "Timed out at https://app.test/path?[REDACTED]",
        "expected": None,
        "observed": "Timed out at https://app.test/path?[REDACTED]",
        "reason": "Kova classified error code NETWORK_ERROR as network or application server.",
        "next_step": "Inspect the recorded request or navigation outcome; this alone does not establish an application defect.",
        "hypothesis": None,
    }


def test_classifies_flow_configuration_and_dispatch_failures():
    assert classify_failure("FLOW_NOT_RUNNABLE") == "flow_configuration"
    assert classify_failure("FLOW_EMPTY_NO_AGENT") == "flow_configuration"
    assert classify_failure("DISPATCH_ERROR") == "dispatch_infrastructure"
    assert classify_failure("ORG_AT_CAPACITY") == "quota_exceeded"


def test_diagnoses_new_failure_codes_with_actionable_next_steps():
    flow_diag = diagnose_failure("FLOW_NOT_RUNNABLE", "no steps")
    assert flow_diag["category"] == "flow_configuration"
    assert "AGENT_EXECUTION_ENABLED" in flow_diag["next_step"]

    dispatch_diag = diagnose_failure("DISPATCH_ERROR", "celery down")
    assert dispatch_diag["category"] == "dispatch_infrastructure"
    assert dispatch_diag["next_step"]

    quota_diag = diagnose_failure("ORG_AT_CAPACITY", "concurrency limit")
    assert quota_diag["category"] == "quota_exceeded"
    assert quota_diag["next_step"]


def test_classifies_ai_provider_failures_separately_from_flow_configuration():
    assert classify_failure("AI_PROVIDER_MISCONFIGURED") == "ai_provider_misconfigured"
    assert classify_failure("AI_PLANNING_FAILED") == "ai_planning"

    misconfig = diagnose_failure("AI_PROVIDER_MISCONFIGURED", "invalid api key for gemini")
    assert misconfig["category"] == "ai_provider_misconfigured"
    assert "provider key" in misconfig["next_step"].lower()

    planning = diagnose_failure("AI_PLANNING_FAILED", "planner returned nothing")
    assert planning["category"] == "ai_planning"
    assert planning["next_step"]


def test_flow_configuration_advice_is_provider_agnostic():
    flow_diag = diagnose_failure("FLOW_NOT_RUNNABLE", "no steps")
    assert "any AI provider" in flow_diag["next_step"]
    assert "GEMINI_API_KEY" in flow_diag["next_step"]
    assert "AGENT_EXECUTION_ENABLED" in flow_diag["next_step"]


def test_redacts_common_secrets_from_diagnostic_text():
    assert sanitize_text("password=hunter2 Bearer eyJtoken") == "password=[REDACTED] Bearer [REDACTED]"
    assert sanitize_payload({"nested": [{"access_key": "abc", "message": "token=xyz"}]}) == {
        "nested": [{"access_key": "[REDACTED]", "message": "token=[REDACTED]"}]
    }


def test_timeline_pairs_action_and_verification_in_sequence():
    events = [
        SimpleNamespace(event_type="action.started", payload={"step": 1, "step_id": "step-b", "type": "click", "target": "Save", "expected_outcome": "record appears"}, created_at=None),
        SimpleNamespace(event_type="action.completed", payload={"step": 1, "step_id": "step-b", "duration_ms": 22, "url": "https://app.test/items?token=secret"}, created_at=None),
        SimpleNamespace(event_type="verification.failed", payload={"step": 1, "step_id": "step-b", "checks": [{"passed": False, "expected": "record appears"}]}, created_at=None),
    ]
    result = build_timeline(events)
    assert len(result) == 1
    assert result[0]["status"] == "failed"
    assert result[0]["duration_ms"] == 22
    assert result[0]["url"] == "https://app.test/items?[REDACTED]"


def test_verification_diagnosis_uses_recorded_expected_and_observed_values():
    report = diagnose_verification({"type": "text", "passed": False, "expected": "Saved", "actual": "Error"}, "Save item")
    assert report["expected"] == "Saved"
    assert report["observed"] == "Error"
    assert report["category"] == "application_behavior"
    assert report["hypothesis"] is None
