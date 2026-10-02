"""Engine state machine tests for pause / human control / resume."""

import pytest

from app.engine.execution.state import (
    ExecutionState,
    InvalidTransitionError,
    is_terminal,
    validate_transition,
    VALID_TRANSITIONS,
)


class TestPauseLifecycle:
    def test_running_to_paused(self):
        validate_transition(ExecutionState.RUNNING, ExecutionState.PAUSED)

    def test_paused_to_human_controlled(self):
        validate_transition(ExecutionState.PAUSED, ExecutionState.HUMAN_CONTROLLED)

    def test_human_controlled_to_resuming(self):
        validate_transition(ExecutionState.HUMAN_CONTROLLED, ExecutionState.RESUMING)

    def test_resuming_to_running(self):
        validate_transition(ExecutionState.RESUMING, ExecutionState.RUNNING)

    def test_running_to_human_controlled_shortcut(self):
        validate_transition(ExecutionState.RUNNING, ExecutionState.HUMAN_CONTROLLED)

    def test_paused_cannot_skip_to_running(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(ExecutionState.PAUSED, ExecutionState.RUNNING)


class TestDbStateMachinePause:
    def test_db_paused_to_human_controlled(self):
        from app.modules.executions.state_machine import validate_transition as db_vt
        db_vt("PAUSED", "HUMAN_CONTROLLED")

    def test_db_human_controlled_to_resuming(self):
        from app.modules.executions.state_machine import validate_transition as db_vt
        db_vt("HUMAN_CONTROLLED", "RESUMING")

    def test_db_unverified_is_terminal(self):
        from app.modules.executions.state_machine import is_terminal, TERMINAL_STATES
        assert "UNVERIFIED" in TERMINAL_STATES
        assert is_terminal("UNVERIFIED") is True

    def test_db_blocked_is_terminal(self):
        from app.modules.executions.state_machine import is_terminal
        assert is_terminal("BLOCKED") is True

    def test_db_running_to_unverified(self):
        from app.modules.executions.state_machine import validate_transition as db_vt
        db_vt("RUNNING", "UNVERIFIED")

    def test_db_running_to_blocked(self):
        from app.modules.executions.state_machine import validate_transition as db_vt
        db_vt("RUNNING", "BLOCKED")


class TestTerminal:
    def test_completed_terminal(self):
        assert is_terminal(ExecutionState.COMPLETED) is True

    def test_failed_terminal(self):
        assert is_terminal(ExecutionState.FAILED) is True

    def test_running_not_terminal(self):
        assert is_terminal(ExecutionState.RUNNING) is False


class TestAllEngineStatesCovered:
    def test_all_states_have_transitions(self):
        for state in ExecutionState:
            assert state in VALID_TRANSITIONS
