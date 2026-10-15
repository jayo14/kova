import uuid
from typing import Any

from app.modules.flows.generator.schemas import ExecutionStep
from app.modules.flows.schemas import FlowStateContract


def to_json_representation(
    name: str,
    steps: list[ExecutionStep],
    state_contract: FlowStateContract,
    source: str = "deterministic",
    confidence: float = 1.0,
    page_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    """Serialize a generated flow into a deterministic, diff-able JSON dictionary."""
    return {
        "name": name,
        "steps": [s.model_dump() for s in steps],
        "state_contract": state_contract.model_dump() if state_contract else {},
        "source": source,
        "confidence": round(float(confidence), 3),
        "page_ids": [str(p) for p in (page_ids or [])],
    }


def diff_flows(flow_a: dict[str, Any], flow_b: dict[str, Any]) -> dict[str, Any]:
    """Compute structured semantic diff between two flow JSON representations."""
    diff: dict[str, Any] = {
        "changed_metadata": {},
        "added_steps": [],
        "removed_steps": [],
        "modified_steps": [],
        "state_contract_diff": {},
    }

    # Compare metadata
    for key in ("name", "source", "confidence"):
        val_a = flow_a.get(key)
        val_b = flow_b.get(key)
        if val_a != val_b:
            diff["changed_metadata"][key] = {"from": val_a, "to": val_b}

    # Compare state contract
    sc_a = flow_a.get("state_contract") or {}
    sc_b = flow_b.get("state_contract") or {}
    for sc_key in ("requires", "produces", "mutates", "reset_strategy"):
        if sc_a.get(sc_key) != sc_b.get(sc_key):
            diff["state_contract_diff"][sc_key] = {
                "from": sc_a.get(sc_key),
                "to": sc_b.get(sc_key),
            }

    # Compare steps
    steps_a = flow_a.get("steps") or []
    steps_b = flow_b.get("steps") or []

    min_len = min(len(steps_a), len(steps_b))
    for i in range(min_len):
        s_a = steps_a[i]
        s_b = steps_b[i]
        if s_a != s_b:
            diff["modified_steps"].append({
                "index": i,
                "from": s_a,
                "to": s_b,
            })

    if len(steps_b) > len(steps_a):
        for i in range(len(steps_a), len(steps_b)):
            diff["added_steps"].append({
                "index": i,
                "step": steps_b[i],
            })
    elif len(steps_a) > len(steps_b):
        for i in range(len(steps_b), len(steps_a)):
            diff["removed_steps"].append({
                "index": i,
                "step": steps_a[i],
            })

    return diff
