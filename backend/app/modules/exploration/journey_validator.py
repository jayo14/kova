"""Quality validation, repair, and ranking engine for user journeys.

Enforces strict quality criteria before presenting candidate journeys:
- Distinguishes functional capability tests from shallow page visits
- Rejects generic or vague assertions ("verify visible feedback", "page loaded")
- Grounds steps in observed capabilities and interfaces
- Automatically repairs weak candidates using discovery evidence
- Ranks candidates by true validation value (core capability relevance, assertion quality)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal
from pydantic import BaseModel, Field

from app.modules.exploration.capabilities import DiscoveredCapability
from app.modules.exploration.schemas import DiscoveredMission

logger = logging.getLogger(__name__)

VAGUE_OUTCOME_PATTERNS = [
    re.compile(r"^\s*verify\s+(?:page\s+loaded|navigation\s+works|visible\s+feedback|content\s+renders?|expected\s+results?\s+present)\s*\.?\s*$", re.I),
    re.compile(r"^\s*expected\s+results?\s+present\s*$", re.I),
    re.compile(r"^\s*verify\s+visible\s+feedback\s*$", re.I),
    re.compile(r"^\s*verify\s+page\s+loaded\s*$", re.I),
    re.compile(r"^\s*verify\s+navigation\s*$", re.I),
    re.compile(r"^\s*lands\s+on\s+expected\s+page\s*$", re.I),
]

VALID_STEP_TYPES = {
    "navigate", "click", "type", "fill", "select", "submit", "scroll",
    "wait", "assert_visible", "assert_text", "upload", "press"
}


class QualityDefect(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"]


class JourneyValidationResult(BaseModel):
    is_valid: bool
    defects: list[QualityDefect] = Field(default_factory=list)
    repaired: bool = False


def is_vague_outcome(outcome: str | None) -> bool:
    """Check if an expected outcome string is a rejected generic placeholder."""
    if not outcome or not outcome.strip():
        return True
    cleaned = outcome.strip()
    return any(p.search(cleaned) for p in VAGUE_OUTCOME_PATTERNS)


def is_navigation_only_workflow(mission: DiscoveredMission) -> bool:
    """Detect if a journey only visits a page or clicks a link without functional workflow."""
    steps = mission.steps or []
    # If 0 or 1 step, or only navigate/scroll steps
    non_nav_steps = [
        s for s in steps
        if isinstance(s, dict) and s.get("type") not in ("navigate", "scroll", "wait")
    ]
    if len(non_nav_steps) == 0:
        return True
    # If it's only a click on an <a> navigation link
    if len(non_nav_steps) == 1:
        step = non_nav_steps[0]
        target = str(step.get("target") or "")
        if target.startswith("a:") or target.startswith("a[") or "nav" in target.lower():
            return True
    return False


def validate_journey(
    mission: DiscoveredMission,
    capabilities: list[DiscoveredCapability] | None = None,
) -> JourneyValidationResult:
    """Programmatically inspect a candidate journey against quality requirements."""
    defects: list[QualityDefect] = []

    # 1. Goal clarity
    goal = (mission.user_goal or mission.objective or "").strip()
    if not goal or len(goal) < 8:
        defects.append(QualityDefect(
            code="UNCLEAR_GOAL",
            message="Journey must describe a clear, recognizable user goal",
            severity="error",
        ))

    # 2. Functional relevance vs shallow navigation
    if mission.classification == "functional" and is_navigation_only_workflow(mission):
        # A journey that only navigates to a section and checks a heading is NOT a functional journey
        defects.append(QualityDefect(
            code="SHALLOW_NAVIGATION",
            message="Journey only visits a page without executing a functional workflow",
            severity="error",
        ))

    # 3. Outcome specificity
    raw_outcome = mission.expected_outcome or (
        mission.successCondition if isinstance(mission.successCondition, str) else None
    )
    if is_vague_outcome(raw_outcome):
        # Check if successCondition dict is also trivial
        if isinstance(mission.successCondition, dict):
            # If successCondition is just element_count >= 1 with generic selectors, it is vague
            keys = list(mission.successCondition.keys())
            if keys == ["element_count"]:
                sel = mission.successCondition.get("element_count", {}).get("selector", "")
                if sel in ("a, button", "a[href], button", "div, section, p", "h1, h2, [role='heading']", "main, [role='main'], header, footer, body"):
                    defects.append(QualityDefect(
                        code="VAGUE_OUTCOME",
                        message="Journey has vague, non-specific verification outcome",
                        severity="error",
                    ))
            elif keys == ["url_matches"] and mission.classification == "functional":
                defects.append(QualityDefect(
                    code="VAGUE_OUTCOME",
                    message="Functional journey cannot pass merely by URL change",
                    severity="error",
                ))
        else:
            defects.append(QualityDefect(
                code="VAGUE_OUTCOME",
                message="Expected outcome is empty or generic placeholder",
                severity="error",
            ))

    # 4. Execution compatibility
    for idx, step in enumerate(mission.steps or []):
        if not isinstance(step, dict):
            defects.append(QualityDefect(
                code="INVALID_STEP_FORMAT",
                message=f"Step {idx+1} is not a dictionary",
                severity="error",
            ))
            continue
        stype = step.get("type") or step.get("action")
        if not stype or str(stype).lower() not in VALID_STEP_TYPES:
            defects.append(QualityDefect(
                code="UNSUPPORTED_ACTION",
                message=f"Step {idx+1} has unsupported action type: {stype}",
                severity="error",
            ))

    # 5. Safety check
    name_and_goal = f"{mission.name} {mission.objective} {str(mission.steps)}".lower()
    if any(k in name_and_goal for k in ("delete all", "drop database", "purge all", "format disk", "destroy production")):
        defects.append(QualityDefect(
            code="DESTRUCTIVE_ACTION",
            message="Potentially destructive operation detected without safe context",
            severity="error",
        ))

    # Error severity decides validity
    has_errors = any(d.severity == "error" for d in defects)
    return JourneyValidationResult(is_valid=not has_errors, defects=defects)


def repair_journey(
    mission: DiscoveredMission,
    capabilities: list[DiscoveredCapability] | None = None,
) -> DiscoveredMission:
    """Attempt to repair a weak journey candidate using available discovery evidence."""
    # Find matching capability if available
    matching_cap: DiscoveredCapability | None = None
    if capabilities:
        for cap in capabilities:
            if cap.id == mission.capability_id or cap.name.lower() in mission.name.lower():
                matching_cap = cap
                break

    # 1. Repair Classification: if shallow navigation, classify as navigation
    if is_navigation_only_workflow(mission):
        mission.classification = "navigation"
        if mission.recommended:
            mission.recommended = False

    # 2. Repair Expected Outcome and Success Condition
    if is_vague_outcome(mission.expected_outcome) or not mission.expected_outcome:
        if matching_cap and matching_cap.expected_outcome:
            mission.expected_outcome = matching_cap.expected_outcome
        elif mission.classification == "functional":
            # Synthesize outcome grounded in steps
            action_verbs = [
                s.get("type") for s in mission.steps
                if isinstance(s, dict) and s.get("type") in ("type", "fill", "submit", "click")
            ]
            if "type" in action_verbs or "fill" in action_verbs:
                mission.expected_outcome = (
                    f"Submit valid inputs for {mission.name}, confirm form processing, "
                    f"and verify the resulting state or created item appears."
                )
            else:
                mission.expected_outcome = (
                    f"Execute {mission.name} workflow and verify application state transition "
                    f"with observable UI feedback."
                )
        else:
            mission.expected_outcome = f"Navigate to {mission.name} and verify destination interface rendered."

    # 3. Repair vague success condition dict
    if isinstance(mission.successCondition, dict):
        keys = list(mission.successCondition.keys())
        if keys == ["element_count"]:
            sel = mission.successCondition["element_count"].get("selector", "")
            if sel in ("a, button", "a[href], button", "div, section, p"):
                # Upgrade to require actionable response elements
                mission.successCondition = {
                    "element_count": {
                        "selector": "form, table, [role='table'], [role='article'], [role='dialog'], [role='alert'], .success, .result",
                        "min": 1,
                    }
                }
    elif not mission.successCondition and mission.classification == "functional":
        mission.successCondition = {
            "element_count": {
                "selector": "main, [role='main'], form, table, [role='dialog'], [role='status']",
                "min": 1,
            }
        }

    # 4. User Goal grounding
    if not mission.user_goal:
        mission.user_goal = mission.objective

    return mission


def score_journey(
    mission: DiscoveredMission,
    capabilities: list[DiscoveredCapability] | None = None,
) -> float:
    """Score a journey along validation value dimensions:
    - Core capability relevance (0.35)
    - Outcome significance (0.25)
    - Assertion quality (0.20)
    - Evidence quality & readiness (0.20)
    """
    score = 0.0

    # Dimension 1: Core capability relevance (0.35)
    # Functional journeys testing primary value proposition score highest
    if mission.classification == "functional":
        score += 0.25
        if mission.is_core or mission.category == "feature":
            score += 0.10
    elif mission.classification == "setup" or mission.category == "auth":
        score += 0.10  # Auth is useful setup, but should not outrank core product features
    elif mission.classification == "navigation":
        score += 0.05  # Lowest priority

    # Dimension 2: Outcome significance (0.25)
    # Concrete outcome that verifies business logic vs trivial URL/element existence
    outcome = (mission.expected_outcome or "").lower()
    if not is_vague_outcome(outcome):
        score += 0.15
        if any(k in outcome for k in ("verify resulting", "persisted", "created", "generated", "report", "opened", "submitted")):
            score += 0.10

    # Dimension 3: Assertion quality (0.20)
    if isinstance(mission.successCondition, dict):
        keys = set(mission.successCondition.keys())
        if "record_persisted" in keys or "text_visible" in keys or "auth_verified" in keys:
            score += 0.20
        elif "element_visible" in keys:
            score += 0.15
        elif "element_count" in keys:
            score += 0.10
        elif "url_matches" in keys or "url_changed_to" in keys:
            score += 0.05

    # Dimension 4: Evidence quality & execution readiness (0.20)
    if mission.steps and len(mission.steps) >= 2:
        score += 0.10
    if mission.discovery_evidence:
        score += 0.05
    if (mission.confidence or 0.0) >= 0.7:
        score += 0.05

    return round(score, 3)


def deduplicate_and_rank_journeys(
    missions: list[DiscoveredMission],
    capabilities: list[DiscoveredCapability] | None = None,
    max_results: int = 6,
) -> list[DiscoveredMission]:
    """Validate, repair, deduplicate, score, and rank candidate journeys.
    
    Guarantees:
    - Never recommends shallow navigation or auth as the primary journey when real features exist
    - Rejects invalid or unrepaired journeys
    - Recommends the highest-value functional workflow with an explicit rationale
    """
    validated: list[DiscoveredMission] = []
    seen_keys: set[str] = set()

    for m in missions:
        # Check and attempt repair
        val = validate_journey(m, capabilities)
        if not val.is_valid:
            m = repair_journey(m, capabilities)
            val = validate_journey(m, capabilities)

        # If it's still fundamentally invalid (e.g. destructive or unsupported action), exclude it
        if not val.is_valid:
            logger.info("Excluding invalid journey '%s': %s", m.name, [d.message for d in val.defects])
            continue

        # Deduplication key based on normalized intent and targets
        key = f"{m.classification}:{m.category}:{m.name.strip().lower()}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        validated.append(m)

    if not validated:
        return []

    # Score each validated journey
    scored: list[tuple[float, DiscoveredMission]] = []
    for m in validated:
        s = score_journey(m, capabilities)
        scored.append((s, m))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Designate exactly ONE recommended journey:
    # Must be the highest-scoring functional workflow (never auth/setup or navigation if functional exists)
    results = [m for _, m in scored]
    for m in results:
        m.recommended = False

    primary_candidate = next(
        (m for m in results if m.classification == "functional" and m.category not in ("auth", "navigation")),
        results[0]
    )
    primary_candidate.recommended = True
    primary_candidate.ranking_rationale = (
        f"Selected as highest-value journey: tests core capability '{primary_candidate.name}' "
        f"with verifiable outcome: '{primary_candidate.expected_outcome}'"
    )

    return results[:max_results]
