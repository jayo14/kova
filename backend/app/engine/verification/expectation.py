from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PreRegisteredExpectation:
    expectation_id: str
    objective: str
    derived_from_objective: bool = True
    pre_state_snapshot: dict[str, Any] = field(default_factory=dict)
    postconditions: list[dict[str, Any]] = field(default_factory=list)
    negative_checks: list[dict[str, Any]] = field(default_factory=list)
    requires_persistence_check: bool = False
    requires_network_corroboration: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    locked: bool = True
    evidence_requirements: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "objective": self.objective,
            "derived_from_objective": self.derived_from_objective,
            "pre_state_snapshot": self.pre_state_snapshot,
            "postconditions": self.postconditions,
            "negative_checks": self.negative_checks,
            "requires_persistence_check": self.requires_persistence_check,
            "requires_network_corroboration": self.requires_network_corroboration,
            "created_at": self.created_at,
            "locked": self.locked,
            "evidence_requirements": self.evidence_requirements,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreRegisteredExpectation":
        return cls(
            expectation_id=str(data.get("expectation_id", "")),
            objective=str(data.get("objective", "")),
            derived_from_objective=bool(data.get("derived_from_objective", True)),
            pre_state_snapshot=dict(data.get("pre_state_snapshot") or {}),
            postconditions=list(data.get("postconditions") or []),
            negative_checks=list(data.get("negative_checks") or []),
            requires_persistence_check=bool(data.get("requires_persistence_check", False)),
            requires_network_corroboration=bool(data.get("requires_network_corroboration", False)),
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
            locked=bool(data.get("locked", True)),
            evidence_requirements=list(data.get("evidence_requirements") or []),
        )


def derive_expectation_from_objective(objective: str, page_state: dict[str, Any] | None = None) -> PreRegisteredExpectation:
    import uuid

    objective_str = (objective or "").strip()
    page_state = page_state or {}

    postconditions = []
    negative_checks = [
        {"type": "no_error_banners", "required": True, "evidence": "screenshot"},
        {"type": "no_validation_errors", "required": True, "evidence": "dom_excerpt"},
        {"type": "no_action_tied_errors", "required": True, "evidence": "console_or_network"},
    ]

    lower_obj = objective_str.lower()
    if any(kw in lower_obj for kw in ("create", "add", "submit", "save", "post", "upload")):
        postconditions.append({
            "type": "delta_change",
            "required": True,
            "description": "Observable change from baseline state (record count/list gain or new item containing entered value)",
            "evidence": ["screenshot", "dom_excerpt"],
        })
        postconditions.append({
            "type": "persistence_check",
            "required": True,
            "description": "Change persists after reload/revisit",
            "evidence": ["screenshot_after_reload"],
        })

    if any(kw in lower_obj for kw in ("login", "sign in", "auth")):
        postconditions.append({
            "type": "url_or_state_change",
            "required": True,
            "description": "Authentication state changes from baseline",
            "evidence": ["url_snapshot", "dom_excerpt"],
        })

    if not postconditions:
        postconditions.append({
            "type": "concrete_outcome",
            "required": True,
            "description": "Observable postcondition derived from objective, verifiable from DOM/state change",
            "evidence": ["dom_excerpt", "screenshot"],
        })

    exp = PreRegisteredExpectation(
        expectation_id=str(uuid.uuid4()),
        objective=objective_str,
        pre_state_snapshot={
            "url": page_state.get("url"),
            "title": page_state.get("title"),
            "headings": page_state.get("headings"),
            "counts": page_state.get("counts"),
            "visible_records": page_state.get("visible_records"),
        },
        postconditions=postconditions,
        negative_checks=negative_checks,
        requires_persistence_check=any(p.get("type") == "persistence_check" for p in postconditions),
        requires_network_corroboration=True,
    )
    return exp
