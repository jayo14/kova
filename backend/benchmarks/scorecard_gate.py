"""Fail CI on any planted false pass or a completion regression over 5 points."""

import argparse
import json
from pathlib import Path


def check_scorecard(baseline_path: str, current_path: str) -> tuple[bool, str]:
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = json.loads(Path(current_path).read_text(encoding="utf-8"))
    previous_rate = baseline["metrics"]["completion_rate"]
    current_rate = current["metrics"]["completion_rate"]
    false_pass_rate = current["metrics"]["false_pass_rate"]
    unproven_successes = current["metrics"]["success_without_evidence"]
    if false_pass_rate > 0:
        return False, f"false-pass rate must be 0; observed {false_pass_rate:.1%}"
    if unproven_successes > 0:
        return False, f"success claims without evidence must be 0; observed {unproven_successes}"
    if current_rate < previous_rate - 0.05:
        return False, (
            f"completion rate regressed by more than 5 percentage points: "
            f"{previous_rate:.1%} -> {current_rate:.1%}"
        )
    return True, f"scorecard gates passed ({current_rate:.1%} completion, 0% false pass)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline")
    parser.add_argument("current")
    args = parser.parse_args()
    passed, message = check_scorecard(args.baseline, args.current)
    print(message)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
