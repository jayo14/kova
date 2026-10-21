"""Tests for §14 benchmark harness and Prompt A acceptance checks."""

import pytest
import pytest_asyncio
from benchmarks.runner import BenchmarkRunner
from benchmarks.suites.default import DEFAULT_SUITE, FixtureDef


@pytest_asyncio.fixture(scope="module")
async def benchmark_report():
    """Run benchmark once across all fixtures and share report across assertions."""
    runner = BenchmarkRunner(suite=DEFAULT_SUITE)
    return await runner.run()


def test_benchmark_runner_runs_all_fixtures(benchmark_report):
    assert len(benchmark_report.fixture_results) >= 15
    fixture_ids = {r.fixture_id for r in benchmark_report.fixture_results}
    assert "buggy_contact_form" in fixture_ids
    assert "working_contact_form" in fixture_ids
    assert "buggy_auth_flow" in fixture_ids
    assert "working_auth_flow" in fixture_ids
    assert "permission_escalation" in fixture_ids
    assert "visual_regression" in fixture_ids
    assert "modal_login" in fixture_ids
    assert "multistep_login" in fixture_ids
    assert "redirect_after_login" in fixture_ids
    assert "session_expiry" in fixture_ids
    assert "totp_login" in fixture_ids
    assert "email_otp_login" in fixture_ids
    assert "enrollment_flow" in fixture_ids
    assert "spa_custom_buttons" in fixture_ids
    assert "iframe_login" in fixture_ids


def test_metrics_computed_correctly(benchmark_report):
    m = benchmark_report.metrics
    assert m.scenario_relevance >= 0.80
    assert m.true_positive_rate >= 0.90
    assert m.false_positive_rate <= 0.05
    assert m.evidence_quality_score >= 0.95
    assert m.auth_success_rate >= 0.95
    assert m.flow_completion_rate >= 0.85
    assert m.evidence_completeness >= 0.98
    assert m.cost_per_validation_usd >= 0.0


def test_report_markdown_includes_all_metrics(benchmark_report):
    md = benchmark_report.to_markdown()

    assert "Scenario relevance" in md
    assert "True positive rate" in md
    assert "False positive rate" in md
    assert "Evidence quality" in md
    assert "Auth success rate" in md
    assert "Flow completion rate" in md
    assert "Evidence completeness" in md
    assert "Per-fixture results" in md


def test_known_defect_detected_in_buggy_contact_form(benchmark_report):
    contact_result = next(r for r in benchmark_report.fixture_results if r.fixture_id == "buggy_contact_form")
    assert contact_result.expected_defects == 1
    assert contact_result.detected_defects == 1
    assert contact_result.false_positives == 0
    assert contact_result.false_negatives == 0
    assert contact_result.evidence_valid is True


def test_no_false_positive_in_working_contact_form(benchmark_report):
    working_result = next(r for r in benchmark_report.fixture_results if r.fixture_id == "working_contact_form")
    assert working_result.expected_defects == 0
    assert working_result.detected_defects == 0
    assert working_result.false_positives == 0
    assert working_result.flow_completed is True


def test_pain_fixtures_all_completed_and_verified(benchmark_report):
    results_map = {r.fixture_id: r for r in benchmark_report.fixture_results}

    # Modal login
    modal = results_map["modal_login"]
    assert modal.auth_success is True
    assert modal.flow_completed is True
    assert modal.evidence_valid is True

    # Multi-step login
    mstep = results_map["multistep_login"]
    assert mstep.auth_success is True
    assert mstep.flow_completed is True

    # Redirect after login
    redir = results_map["redirect_after_login"]
    assert redir.auth_success is True
    assert redir.flow_completed is True

    # Session expiry seeded defect
    expiry = results_map["session_expiry"]
    assert expiry.detected_defects == 1
    assert expiry.evidence_valid is True

    # TOTP 2FA
    totp = results_map["totp_login"]
    assert totp.auth_success is True
    assert totp.flow_completed is True

    # Email OTP via temp mail inbox
    email_otp = results_map["email_otp_login"]
    assert email_otp.auth_success is True
    assert email_otp.flow_completed is True

    # Enrollment before access
    enroll = results_map["enrollment_flow"]
    assert enroll.flow_completed is True
    assert enroll.false_positives == 0

    # SPA with custom div buttons
    spa = results_map["spa_custom_buttons"]
    assert spa.flow_completed is True
    assert spa.false_positives == 0

    # Iframe login
    iframe = results_map["iframe_login"]
    assert iframe.auth_success is True
    assert iframe.flow_completed is True


@pytest.mark.asyncio
async def test_breaking_auth_causes_benchmark_failure():
    """Acceptance check: breaking login makes the benchmark fail."""
    # When given a broken fixture with bad password, it records failure
    broken_fixture = FixtureDef(
        fixture_id="working_auth_flow",
        description="Test broken auth detection",
        known_defects=[],
        expected_scenarios=["Login"],
        app_module="benchmarks.fixtures.buggy_auth_flow.app",  # Point to buggy app as working
        path=DEFAULT_SUITE.fixtures[0].path,
    )
    runner = BenchmarkRunner(suite=type(DEFAULT_SUITE)(name="broken_test", fixtures=[broken_fixture]))
    report = await runner.run()

    # The clean fixture fails authentication -> generates a false positive
    res = report.fixture_results[0]
    assert res.auth_success is False
    assert res.false_positives == 1
    assert report.metrics.false_positive_rate > 0.0
