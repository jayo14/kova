"""Deterministic assertion-level regression comparison for suite runs."""

from __future__ import annotations

import json
from typing import Any

PASSING = {"passed", "pass", "success", "completed"}
FAILING = {"failed", "fail", "error"}
INCONCLUSIVE = {"blocked", "unverified", "error", "skipped", "timeout", "cancelled"}


def normalize_assertions(raw: list[dict] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        check_type = str(item.get("type") or item.get("kind") or "unknown")
        raw_key = item.get("key")
        if raw_key:
            base = str(raw_key)
        else:
            expected = item.get("expected")
            expected_text = (
                json.dumps(expected, sort_keys=True, default=str)
                if expected is not None
                else ""
            )
            base = f"{check_type}:{expected_text}"
        occurrence = seen.get(base, 0)
        seen[base] = occurrence + 1
        key = base if occurrence == 0 else f"{base}#{occurrence}"
        normalized.append(
            {
                "key": key,
                "type": check_type,
                "passed": bool(item.get("passed")),
                "message": item.get("message") or "",
                "expected": item.get("expected"),
                "actual": item.get("actual"),
            }
        )
    return normalized


def assertions_from_events(events: list[Any]) -> list[dict[str, Any]]:
    """Extract checks from the latest verification event of an execution."""
    from app.modules.executions.event_types import EventTypes

    verification_types = {
        EventTypes.VERIFICATION_PASSED,
        EventTypes.VERIFICATION_FAILED,
        "verification_passed",
        "verification_failed",
    }
    for event in reversed(events or []):
        if getattr(event, "event_type", None) not in verification_types:
            continue
        payload = getattr(event, "payload", None) or {}
        checks = payload.get("checks") if isinstance(payload, dict) else None
        if checks:
            return normalize_assertions(checks)
    return []


def failure_signature(status: str, assertions: list[dict]) -> str | None:
    if status in PASSING or status == "skipped":
        return None
    failed = sorted(item["key"] for item in assertions if not item.get("passed"))
    if failed:
        return f"assertions:{'|'.join(failed[:8])}"
    return f"status:{status}"


def _status_class(status: str) -> str:
    if status in PASSING:
        return "pass"
    if status in FAILING:
        return "fail"
    return "inconclusive"


def _compare_assertions(
    baseline: list[dict], current: list[dict]
) -> tuple[str | None, list[dict]]:
    base_map = {item["key"]: item for item in baseline}
    cur_map = {item["key"]: item for item in current}
    details: list[dict] = []
    classification: str | None = None

    for key in sorted(set(base_map) | set(cur_map)):
        before = base_map.get(key)
        after = cur_map.get(key)
        if before is None:
            details.append(
                {
                    "kind": "assertion_added",
                    "check_key": key,
                    "type": after["type"],
                    "baseline_passed": None,
                    "current_passed": after["passed"],
                    "message": "Assertion is new in this run",
                }
            )
            classification = classification or "changed_test"
        elif after is None:
            details.append(
                {
                    "kind": "assertion_removed",
                    "check_key": key,
                    "type": before["type"],
                    "baseline_passed": before["passed"],
                    "current_passed": None,
                    "message": "Assertion no longer present",
                }
            )
            classification = classification or "changed_test"
        elif before["passed"] and not after["passed"]:
            details.append(
                {
                    "kind": "assertion_failed",
                    "check_key": key,
                    "type": after["type"],
                    "baseline_passed": True,
                    "current_passed": False,
                    "message": after.get("message")
                    or "Previously passing assertion failed",
                }
            )
            classification = "new_failure"
        elif not before["passed"] and after["passed"]:
            details.append(
                {
                    "kind": "assertion_recovered",
                    "check_key": key,
                    "type": after["type"],
                    "baseline_passed": False,
                    "current_passed": True,
                    "message": "Previously failing assertion now passes",
                }
            )
            if classification != "new_failure":
                classification = "recovered_failure"
    return classification, details


def compare_runs(
    *,
    baseline_run_id: str | None,
    baseline_reason: str | None,
    baseline_items: list[dict[str, Any]] | None,
    current_items: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_by_flow = {
        str(item.get("flow_id")): item
        for item in (baseline_items or [])
        if item.get("flow_id")
    }
    current_ids = {
        str(item.get("flow_id")) for item in current_items if item.get("flow_id")
    }

    flows: list[dict[str, Any]] = []
    counts = {
        "new_failure": 0,
        "persistent_failure": 0,
        "recovered_failure": 0,
        "new_coverage": 0,
        "removed_coverage": 0,
        "changed_test": 0,
        "inconclusive": 0,
        "stable": 0,
    }

    for item in current_items:
        flow_id = str(item.get("flow_id")) if item.get("flow_id") else None
        baseline = baseline_by_flow.get(flow_id) if flow_id else None
        current_assertions = normalize_assertions(item.get("assertions"))
        current_status = str(item.get("status") or "error")

        if baseline is None:
            category = "new_coverage"
            details = []
        else:
            baseline_status = str(baseline.get("status") or "error")
            before_assertions = normalize_assertions(baseline.get("assertions"))
            category, details = _compare_assertions(
                before_assertions, current_assertions
            )
            before_class = _status_class(baseline_status)
            after_class = _status_class(current_status)
            if category is None:
                if after_class == "inconclusive" or before_class == "inconclusive":
                    category = "inconclusive"
                elif before_class == "pass" and after_class == "fail":
                    category = "new_failure"
                elif before_class == "fail" and after_class == "pass":
                    category = "recovered_failure"
                elif before_class == "fail" and after_class == "fail":
                    category = "persistent_failure"
                else:
                    category = "stable"
            elif (
                category in ("new_failure", "recovered_failure")
                and after_class == "inconclusive"
            ):
                category = "inconclusive"

        counts[category] += 1
        flows.append(
            {
                "flow_id": flow_id,
                "flow_name": item.get("flow_name"),
                "classification": category,
                "baseline_status": baseline.get("status") if baseline else None,
                "current_status": current_status,
                "details": details,
            }
        )
        item["classification"] = category

    if baseline_items is not None:
        for item in baseline_items:
            flow_id = str(item.get("flow_id")) if item.get("flow_id") else None
            if not flow_id or flow_id in current_ids:
                continue
            counts["removed_coverage"] += 1
            flows.append(
                {
                    "flow_id": flow_id,
                    "flow_name": item.get("flow_name"),
                    "classification": "removed_coverage",
                    "baseline_status": item.get("status"),
                    "current_status": None,
                    "details": [],
                }
            )

    if counts["new_failure"] > 0:
        verdict = "regression"
    elif counts["inconclusive"] > 0:
        verdict = "inconclusive"
    elif counts["recovered_failure"] > 0:
        verdict = "improved"
    else:
        verdict = "unchanged"

    explanation: list[str] = []
    if counts["new_failure"]:
        explanation.append(f"{counts['new_failure']} flow(s) newly failing")
    if counts["persistent_failure"]:
        explanation.append(
            f"{counts['persistent_failure']} flow(s) already failing in baseline"
        )
    if counts["recovered_failure"]:
        explanation.append(f"{counts['recovered_failure']} flow(s) recovered")
    if counts["new_coverage"]:
        explanation.append(f"{counts['new_coverage']} flow(s) not present in baseline")
    if counts["removed_coverage"]:
        explanation.append(f"{counts['removed_coverage']} flow(s) no longer covered")
    if counts["changed_test"]:
        explanation.append(f"{counts['changed_test']} flow(s) changed assertions")
    if counts["inconclusive"]:
        explanation.append(f"{counts['inconclusive']} flow(s) inconclusive")

    return {
        "baseline_run_id": baseline_run_id,
        "baseline_reason": baseline_reason,
        "verdict": verdict,
        "counts": counts,
        "flows": flows,
        "explanation": explanation,
    }
