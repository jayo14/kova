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
