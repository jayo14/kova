"""Unit tests for human-only challenge detection and the runner handoff gate.

Covers the deterministic classifier (generic DOM markers only, no secrets) and
the runner behaviour: pause for a human, never solve or bypass, and never loop
forever when the challenge is not cleared.
"""

import pytest

from app.engine.ai.schemas import HumanChallengeClassification
from app.engine.browser import auth as auth_module
from app.engine.browser.auth import AuthSignalBundle, classify_human_challenge
from app.engine.execution import control as control_module
from app.engine.execution import runner as runner_module
from app.engine.execution.runner import ExecutionError, FlowRunner
from app.engine.execution.state import ExecutionState


def _bundle(**overrides) -> AuthSignalBundle:
    base = dict(
        url_path_is_auth=False,
        visible_password_input_count=0,
        visible_email_input_count=0,
        visible_otp_input_count=0,
        has_remember_me_checkbox=False,
        has_forgot_password_link=False,
    )
    base.update(overrides)
    return AuthSignalBundle(**base)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def test_captcha_takes_precedence_over_every_other_marker():
    result = classify_human_challenge(
        _bundle(
            captcha_markers=["captcha_widget"],
            payment_markers=["card_field"],
            mfa_push_markers=["approve sign-in"],
            passkey_markers=["use passkey"],
        )
    )
    assert isinstance(result, HumanChallengeClassification)
    assert result.kind == "captcha_bot_check"


def test_payment_prompt_beats_mfa_and_passkey():
    result = classify_human_challenge(
        _bundle(
            payment_markers=["card_field"],
            mfa_push_markers=["approve sign-in"],
            passkey_markers=["use passkey"],
        )
    )
    assert result.kind == "payment_prompt"


def test_mfa_push_beats_passkey():
    result = classify_human_challenge(
        _bundle(mfa_push_markers=["check your phone"], passkey_markers=["use passkey"])
    )
    assert result.kind == "mfa_push"


def test_passkey_is_a_challenge_only_without_a_usable_password_form():
    result = classify_human_challenge(_bundle(passkey_markers=["sign in with passkey"]))
    assert result.kind == "passkey"

    not_blocking = classify_human_challenge(
        _bundle(passkey_markers=["sign in with passkey"], visible_password_input_count=1)
    )
    assert not_blocking is None

    otp_present = classify_human_challenge(
        _bundle(passkey_markers=["sign in with passkey"], visible_otp_input_count=1)
    )
    assert otp_present is None


def test_plain_login_and_signup_pages_are_not_challenges():
    assert classify_human_challenge(_bundle(visible_password_input_count=1, visible_email_input_count=1)) is None
    assert classify_human_challenge(_bundle(url_path_is_auth=True, has_forgot_password_link=True)) is None
    assert classify_human_challenge(_bundle()) is None


def test_evidence_never_carries_secrets_and_is_capped():
    result = classify_human_challenge(
        _bundle(captcha_markers=["a", "b", "c", "d", "e"])
    )
    assert result.evidence == {"markers": ["a", "b", "c"]}


def test_bundle_marker_lists_are_not_shared_between_instances():
    first = _bundle()
    second = _bundle()
    first.captcha_markers.append("captcha_widget")
    assert second.captcha_markers == []


# ---------------------------------------------------------------------------
# Runner gate
# ---------------------------------------------------------------------------

class _FakeCtx:
    def __init__(self):
        self.execution_id = "exec_test"
        self.state = ExecutionState.OBSERVING
        self.events = []
        self.transitions = []

    def record_event(self, event_type, payload=None):
        self.events.append((event_type, payload or {}))

    def transition(self, state):
        self.state = state
        self.transitions.append(state)


class _FakePage:
    def __init__(self, url="https://example.test/challenge"):
        self.url = url


class _FakeBrowser:
    def __init__(self, started=True):
        self.page = _FakePage()
        self.is_started = started


class _GateHarness(FlowRunner):
    """FlowRunner with pause/event plumbing stubbed out."""

    def __init__(self, resume_sequence):
        self._resume_sequence = list(resume_sequence)
        self.pause_calls = 0
        self.checkpoints = []

    async def _check_and_handle_pause(self, ctx, browser, execution_id, event_recorder):
        self.pause_calls += 1
        return self._resume_sequence.pop(0) if self._resume_sequence else False

    async def _emit_events(self, ctx, event_recorder):
        return None


@pytest.fixture
def challenge_detector(monkeypatch):
    """Patch the detector plus control helpers used by the gate."""
    state = {"results": [], "calls": 0}

    async def fake_detect(page, url=None):
        state["calls"] += 1
        if state["results"]:
            return state["results"].pop(0)
        return None

    checkpoint_calls = []

    async def fake_raise_human_checkpoint(**kwargs):
        checkpoint_calls.append(kwargs)

    cancelled = {"value": False}

    async def fake_is_cancel_requested(execution_id):
        return cancelled["value"]

    # `detect_human_challenge` and `raise_human_checkpoint` are imported inside
    # the gate body, so patch their defining modules rather than the runner.
    monkeypatch.setattr(auth_module, "detect_human_challenge", fake_detect)
    monkeypatch.setattr(control_module, "raise_human_checkpoint", fake_raise_human_checkpoint)
    monkeypatch.setattr(runner_module, "is_cancel_requested", fake_is_cancel_requested)

    state["checkpoint_calls"] = checkpoint_calls
    state["cancelled"] = cancelled
    return state


def _captcha():
    return HumanChallengeClassification(
        kind="captcha_bot_check",
        confidence=1.0,
        description="A CAPTCHA or bot-verification challenge is blocking this page.",
        evidence={"markers": ["captcha_widget"]},
    )


async def test_gate_pauses_for_human_then_blocks_when_still_unresolved(challenge_detector):
    challenge_detector["results"] = [_captcha(), _captcha(), _captcha()]
    harness = _GateHarness(resume_sequence=[True, True])
    ctx = _FakeCtx()

    with pytest.raises(ExecutionError) as excinfo:
        await harness._enforce_human_challenge_gate(ctx, _FakeBrowser(), 4, None)

    assert excinfo.value.error_code == "HUMAN_CHALLENGE_UNRESOLVED"
    assert harness.pause_calls == 2
    assert ctx.state == ExecutionState.BLOCKED
    assert len(challenge_detector["checkpoint_calls"]) == 2
    assert challenge_detector["checkpoint_calls"][0]["checkpoint_type"] == "captcha_bot_check"
    assert "url" in challenge_detector["checkpoint_calls"][0]["details"]
    assert any(
        payload.get("checkpoint_type") == "captcha_bot_check"
        for _, payload in ctx.events
    )


async def test_gate_resumes_when_human_clears_the_challenge(challenge_detector):
    challenge_detector["results"] = [_captcha(), None]
    harness = _GateHarness(resume_sequence=[True])
    ctx = _FakeCtx()

    await harness._enforce_human_challenge_gate(ctx, _FakeBrowser(), 2, None)

    assert harness.pause_calls == 1
    assert ctx.state != ExecutionState.BLOCKED


async def test_gate_stops_without_raising_when_cancelled(challenge_detector):
    challenge_detector["results"] = [_captcha()]
    challenge_detector["cancelled"]["value"] = True
    harness = _GateHarness(resume_sequence=[True])
    ctx = _FakeCtx()

    await harness._enforce_human_challenge_gate(ctx, _FakeBrowser(), 1, None)

    assert harness.pause_calls == 0
    assert challenge_detector["checkpoint_calls"] == []


async def test_gate_stops_when_pause_does_not_resume(challenge_detector):
    challenge_detector["results"] = [_captcha()]
    harness = _GateHarness(resume_sequence=[False])
    ctx = _FakeCtx()

    await harness._enforce_human_challenge_gate(ctx, _FakeBrowser(), 1, None)

    assert harness.pause_calls == 1
    assert harness._resume_sequence == []


async def test_gate_is_a_noop_without_a_challenge(challenge_detector):
    challenge_detector["results"] = [None]
    harness = _GateHarness(resume_sequence=[])
    ctx = _FakeCtx()

    await harness._enforce_human_challenge_gate(ctx, _FakeBrowser(), 1, None)

    assert harness.pause_calls == 0
    assert challenge_detector["checkpoint_calls"] == []


async def test_gate_is_a_noop_before_the_browser_starts(challenge_detector):
    challenge_detector["results"] = [_captcha()]
    harness = _GateHarness(resume_sequence=[True])
    ctx = _FakeCtx()

    await harness._enforce_human_challenge_gate(ctx, _FakeBrowser(started=False), 1, None)

    assert challenge_detector["calls"] == 0
    assert harness.pause_calls == 0
