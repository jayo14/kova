"""Unit tests for pre-registered (pre-action) expectations and evidence-based verdicts.

Covers § "Verification defined before action":
- Expectation is derived before the first action and is locked / immutable.
- Verification condition is built from the pre-registered expectation (write →
  record_persisted with persistence reload + negative checks), never compiled from
  the live page after the run.
- Verdict rules: any hard fail -> FAILED; all hard pass -> COMPLETED; any
  not-evaluable -> UNVERIFIED.
"""
import pytest
from app.engine.execution.runner import FlowRunner, classify_verification_rejection
from app.engine.verification.expectation import PreRegisteredExpectation, derive_expectation_from_objective
from app.engine.verification.verifier import VerificationResult, VerificationCheck

runner = FlowRunner()


def test_extract_expected_value():
    assert runner._extract_expected_value("Create a new record with title 'Hello World'") == "Hello World"
    assert runner._extract_expected_value("Submit the form with value \"42\"") == "42"
    assert runner._extract_expected_value("Enter user@example.com") == "user@example.com"
    assert runner._extract_expected_value("Check the dashboard") == ""


def test_build_verification_condition_write_with_persistence():
    pre_reg = derive_expectation_from_objective("Create a new record with title 'Hello World'", {})
    assert pre_reg.locked is True
    assert pre_reg.requires_persistence_check is True

    condition = runner._build_verification_condition(pre_reg, "Create a new record with title 'Hello World'")
    assert condition is not None
    assert "record_persisted" in condition
    assert condition["record_persisted"]["expected_text"] == "Hello World"
    assert condition["record_persisted"]["reload"] is True
    assert condition["app_error_absent"] is True


def test_build_verification_condition_read_no_persistence():
    pre_reg = derive_expectation_from_objective("View the settings page", {})
    assert pre_reg.requires_persistence_check is False

    condition = runner._build_verification_condition(pre_reg, "View the settings page")
    assert condition is not None
    assert "record_persisted" not in condition
    assert condition["app_error_absent"] is True


def test_build_verification_condition_none_prereg():
    assert runner._build_verification_condition(None, "Create record") is None


def test_classify_verification_rejection_hard_fail_is_failed():
    checks = [
        VerificationCheck(type="record_persisted", passed=False, expected="Hello World", actual="missing"),
        VerificationCheck(type="app_error_absent", passed=True),
    ]
    result = VerificationResult(passed=False, checks=checks)
    assert classify_verification_rejection(result) == "FAILED"


def test_classify_verification_rejection_only_inconclusive_is_unverified():
    checks = [
        VerificationCheck(type="unknown_condition", passed=False),
        VerificationCheck(type="empty_condition", passed=False),
    ]
    result = VerificationResult(passed=False, checks=checks)
    assert classify_verification_rejection(result) == "UNVERIFIED"


def test_all_hard_checks_pass_is_completed():
    checks = [
        VerificationCheck(type="record_persisted", passed=True, expected="Hello World"),
        VerificationCheck(type="app_error_absent", passed=True),
    ]
    result = VerificationResult(passed=True, checks=checks)
    assert result.passed is True
    assert classify_verification_rejection(result) != "FAILED"
