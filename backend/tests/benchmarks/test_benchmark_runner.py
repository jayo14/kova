"""Tests for §14 benchmark harness."""

import pytest
from benchmarks.runner import BenchmarkRunner
from benchmarks.suites.default import DEFAULT_SUITE


@pytest.mark.asyncio
async def test_benchmark_runner_runs_all_fixtures():
    runner = BenchmarkRunner(suite=DEFAULT_SUITE)
    report = await runner.run()

    assert len(report.fixture_results) >= 5
    fixture_ids = {r.fixture_id for r in report.fixture_results}
    assert "buggy_contact_form" in fixture_ids
    assert "working_contact_form" in fixture_ids
    assert "buggy_auth_flow" in fixture_ids


@pytest.mark.asyncio
async def test_metrics_computed_correctly():
    runner = BenchmarkRunner(suite=DEFAULT_SUITE)
    report = await runner.run()

    assert report.scenario_relevance >= 0.80
    assert report.true_positive_rate >= 0.70
    assert report.false_positive_rate <= 0.15
    assert report.evidence_quality >= 0.85
    assert report.metrics.cost_per_validation_usd >= 0.0


@pytest.mark.asyncio
async def test_report_markdown_includes_all_metrics():
    runner = BenchmarkRunner(suite=DEFAULT_SUITE)
    report = await runner.run()
    md = report.to_markdown()

    assert "Scenario relevance" in md
    assert "True positive rate" in md
    assert "False positive rate" in md
    assert "Evidence quality" in md
    assert "Per-fixture results" in md


@pytest.mark.asyncio
async def test_known_defect_detected_in_buggy_contact_form():
    runner = BenchmarkRunner(suite=DEFAULT_SUITE)
    report = await runner.run()

    contact_result = next(r for r in report.fixture_results if r.fixture_id == "buggy_contact_form")
    assert contact_result.expected_defects == 1
    assert contact_result.detected_defects == 1
    assert contact_result.false_positives == 0
    assert contact_result.false_negatives == 0


@pytest.mark.asyncio
async def test_no_false_positive_in_working_contact_form():
    runner = BenchmarkRunner(suite=DEFAULT_SUITE)
    report = await runner.run()

    working_result = next(r for r in report.fixture_results if r.fixture_id == "working_contact_form")
    assert working_result.expected_defects == 0
    assert working_result.detected_defects == 0
    assert working_result.false_positives == 0
