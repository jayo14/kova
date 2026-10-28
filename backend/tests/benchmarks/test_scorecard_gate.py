import json

from benchmarks.scorecard_gate import check_scorecard


def _write_report(path, completion, false_pass, unproven_successes=0):
    path.write_text(json.dumps({
        "metrics": {
            "completion_rate": completion,
            "false_pass_rate": false_pass,
            "success_without_evidence": unproven_successes,
        }
    }))


def test_scorecard_gate_accepts_within_five_point_regression(tmp_path):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, 0.70, 0)
    _write_report(current, 0.65, 0)
    assert check_scorecard(str(baseline), str(current))[0] is True


def test_scorecard_gate_rejects_false_pass(tmp_path):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, 0.70, 0)
    _write_report(current, 0.70, 0.01)
    passed, message = check_scorecard(str(baseline), str(current))
    assert passed is False
    assert "false-pass" in message


def test_scorecard_gate_rejects_success_without_evidence(tmp_path):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, 0.70, 0)
    _write_report(current, 0.70, 0, unproven_successes=1)
    passed, message = check_scorecard(str(baseline), str(current))
    assert passed is False
    assert "without evidence" in message


def test_scorecard_gate_rejects_completion_regression_over_five_points(tmp_path):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, 0.70, 0)
    _write_report(current, 0.64, 0)
    assert check_scorecard(str(baseline), str(current))[0] is False
