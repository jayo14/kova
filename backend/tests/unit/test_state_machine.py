import pytest

from app.modules.executions.state_machine import (
    InvalidTransitionError,
    is_terminal,
    validate_transition,
    VALID_TRANSITIONS,
)


class TestValidTransitions:
    def test_created_to_queued(self):
        validate_transition("CREATED", "QUEUED")

    def test_queued_to_initializing(self):
        validate_transition("QUEUED", "INITIALIZING")

    def test_initializing_to_browser_ready(self):
        validate_transition("INITIALIZING", "BROWSER_READY")

    def test_initializing_to_failed(self):
        validate_transition("INITIALIZING", "FAILED")

    def test_browser_ready_to_running(self):
        validate_transition("BROWSER_READY", "RUNNING")

    def test_browser_ready_to_failed(self):
        validate_transition("BROWSER_READY", "FAILED")

    def test_running_to_waiting(self):
        validate_transition("RUNNING", "WAITING")

    def test_running_to_completed(self):
        validate_transition("RUNNING", "COMPLETED")

    def test_running_to_failed(self):
        validate_transition("RUNNING", "FAILED")

    def test_running_to_cancelled(self):
        validate_transition("RUNNING", "CANCELLED")

    def test_running_to_timeout(self):
        validate_transition("RUNNING", "TIMEOUT")

    def test_waiting_to_running(self):
        validate_transition("WAITING", "RUNNING")

    def test_waiting_to_failed(self):
        validate_transition("WAITING", "FAILED")

    def test_waiting_to_timeout(self):
        validate_transition("WAITING", "TIMEOUT")


class TestInvalidTransitions:
    def test_created_to_running(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            validate_transition("CREATED", "RUNNING")
        assert exc_info.value.current_status == "CREATED"
        assert exc_info.value.attempted_status == "RUNNING"

    def test_created_to_completed(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("CREATED", "COMPLETED")

    def test_queued_to_running(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("QUEUED", "RUNNING")

    def test_initializing_to_running(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("INITIALIZING", "RUNNING")

    def test_browser_ready_to_completed(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("BROWSER_READY", "COMPLETED")

    def test_running_to_created(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("RUNNING", "CREATED")

    def test_waiting_to_created(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("WAITING", "CREATED")

    def test_waiting_to_completed(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("WAITING", "COMPLETED")


class TestTerminalStates:
    def test_completed_is_terminal(self):
        assert is_terminal("COMPLETED") is True

    def test_failed_is_terminal(self):
        assert is_terminal("FAILED") is True

    def test_cancelled_is_terminal(self):
        assert is_terminal("CANCELLED") is True

    def test_timeout_is_terminal(self):
        assert is_terminal("TIMEOUT") is True

    def test_created_not_terminal(self):
        assert is_terminal("CREATED") is False

    def test_running_not_terminal(self):
        assert is_terminal("RUNNING") is False

    def test_waiting_not_terminal(self):
        assert is_terminal("WAITING") is False


class TestTerminalStateNoTransitions:
    def test_completed_no_transitions(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("COMPLETED", "RUNNING")

    def test_failed_no_transitions(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("FAILED", "QUEUED")

    def test_cancelled_no_transitions(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("CANCELLED", "INITIALIZING")

    def test_timeout_no_transitions(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("TIMEOUT", "BROWSER_READY")


class TestRepeatedCompletion:
    def test_completed_to_completed_invalid(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("COMPLETED", "COMPLETED")


class TestCancellation:
    def test_cancel_from_running(self):
        validate_transition("RUNNING", "CANCELLED")

    def test_cancel_from_waiting(self):
        validate_transition("WAITING", "CANCELLED")


class TestTimeout:
    def test_timeout_from_running(self):
        validate_transition("RUNNING", "TIMEOUT")

    def test_timeout_from_waiting(self):
        validate_transition("WAITING", "TIMEOUT")


class TestAllStatesHaveTransitionsDefined:
    def test_all_statuses_covered(self):
        from app.modules.executions.models import ExecutionStatus

        for status in ExecutionStatus:
            assert status.value in VALID_TRANSITIONS
