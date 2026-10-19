"""Per-mode success criteria definitions for Kova's 5 validation modes."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel

from app.modules.validation.models import ValidationMode


class SuccessCriteria(BaseModel):
    mode: ValidationMode
    required_assertions: list[str]          # which assertion types must pass
    optional_assertions: list[str]          # which contribute evidence but not pass/fail
    failure_tolerance: Literal["zero", "bounded", "investigative"]
    # zero: any failure = mode failure (functional, workflow, regression)
    # bounded: up to N failures acceptable (exploratory — discoveries are good)
    # investigative: failures are the point (visual when looking for defects)
    evidence_required: list[Literal["screenshot", "network_log", "dom_snapshot", "video", "trace"]]
    max_duration_seconds: int
    max_turns: int                          # for agent-loop runs


FUNCTIONAL_CRITERIA = SuccessCriteria(
    mode=ValidationMode.FUNCTIONAL,
    required_assertions=["state_transition", "postcondition"],
    optional_assertions=["network_success"],
    failure_tolerance="zero",
    evidence_required=["screenshot", "network_log"],
    max_duration_seconds=300,
    max_turns=30,
)

WORKFLOW_CRITERIA = SuccessCriteria(
    mode=ValidationMode.WORKFLOW,
    required_assertions=["state_transition", "postcondition", "downstream_effect"],
    optional_assertions=["network_success", "persistence_after_reload"],
    failure_tolerance="zero",
    evidence_required=["screenshot", "network_log", "dom_snapshot"],
    max_duration_seconds=600,
    max_turns=60,
)

REGRESSION_CRITERIA = SuccessCriteria(
    mode=ValidationMode.REGRESSION,
    required_assertions=["baseline_match"],  # compared against last-known-good
    optional_assertions=[],
    failure_tolerance="zero",
    evidence_required=["screenshot"],
    max_duration_seconds=300,
    max_turns=30,
)

EXPLORATORY_CRITERIA = SuccessCriteria(
    mode=ValidationMode.EXPLORATORY,
    required_assertions=[],  # exploration has no required pass
    optional_assertions=["unexpected_behavior_detected", "defect_discovered"],
    failure_tolerance="investigative",  # discoveries are good
    evidence_required=["screenshot", "network_log", "dom_snapshot", "video"],
    max_duration_seconds=900,
    max_turns=80,  # allow more turns for investigation
)

VISUAL_CRITERIA = SuccessCriteria(
    mode=ValidationMode.VISUAL,
    required_assertions=["visual_reference_match"],  # impl in action 10
    optional_assertions=["layout_no_overflow", "color_contrast_ok"],
    failure_tolerance="zero",
    evidence_required=["screenshot"],
    max_duration_seconds=180,
    max_turns=15,
)

SUCCESS_CRITERIA: dict[ValidationMode, SuccessCriteria] = {
    ValidationMode.FUNCTIONAL: FUNCTIONAL_CRITERIA,
    ValidationMode.WORKFLOW: WORKFLOW_CRITERIA,
    ValidationMode.REGRESSION: REGRESSION_CRITERIA,
    ValidationMode.EXPLORATORY: EXPLORATORY_CRITERIA,
    ValidationMode.VISUAL: VISUAL_CRITERIA,
}
