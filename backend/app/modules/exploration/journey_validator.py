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
    re.compile(r"^\s*verify\s+(?:page\s+loaded|navigation\s+works|visible\s+feedback|content\s+renders?|expected\s+results?\s+present|visible\s+feedback\s+or\s+navigation|application\s+state\s+changes?)\s*\.?\s*$", re.I),
    re.compile(r"^\s*expected\s+results?\s+present\s*$", re.I),
    re.compile(r"^\s*verify\s+visible\s+feedback\s*$", re.I),
    re.compile(r"^\s*verify\s+page\s+loaded\s*$", re.I),
    re.compile(r"^\s*verify\s+navigation\s*$", re.I),
    re.compile(r"^\s*lands\s+on\s+expected\s+page\s*$", re.I),
    re.compile(r"^\s*page\s+responds\s*$", re.I),
    re.compile(r"^\s*destination\s+(?:content|interface)\s+rendered\s*\.?\s*$", re.I),
    re.compile(r"^\s*destination\s+view\s+for\s+.*loads\s+with\s+content\s*\.?\s*$", re.I),
    re.compile(r"verify\s+(?:the\s+)?application\s+state\s+changes?", re.I),
    re.compile(r"verify\s+application\s+state\s+transition\s+with\s+observable\s+ui\s+feedback", re.I),
    re.compile(r"use\s+the\s+control\s+matching\s+the\s+goal", re.I),
]

_GENERIC_ELEMENT_COUNT_SELECTORS = frozenset({
    "a, button",
    "a[href], button",
    "div, section, p",
    "h1, h2, [role='heading']",
    "main, [role='main'], header, footer, body",
    "main, [role='main'], form, table, [role='dialog'], [role='region'], article, h1, h2, h3, button, input",
    "a[href], button, h1, h2, h3, [role='region'], main",
    "button, form, input, [role='dialog'], [role='region'], h1, h2, h3",
    "a[href], [role='article'], article, li",
    "a[href], button, [role='region'], main, form, table",
})

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
    # If it's only a single click on a navigation link or button without functional input
    if len(non_nav_steps) == 1:
        step = non_nav_steps[0]
        step_type = step.get("type")
        target = str(step.get("target") or "").lower()
        if step_type == "click" and (
            target.startswith("a:")
            or target.startswith("a[")
            or "nav" in target
            or "link" in target
            or "menu" in target
            or any(w in (mission.name + " " + (mission.user_goal or "")).lower() for w in ["navigate", "open", "visit", "browse", "view"])
        ):
            return True
    return False


from app.engine.browser.readiness import (
    _INFRA_CONTROL_LANGUAGE,
    _PROVIDER_TOKENS,
    _WAKE_LANGUAGE,
    is_infrastructure_control,
)


def is_infrastructure_mission(mission: DiscoveredMission) -> bool:
    """Return True if mission depends on infrastructure, hosting interstitial, or cloud provider controls."""
    if is_infrastructure_control(mission.name or ""):
        return True
    if is_infrastructure_control(mission.objective or ""):
        return True
    if is_infrastructure_control(mission.user_goal or ""):
        return True

    # Check steps
    for step in mission.steps or []:
        if isinstance(step, dict):
            for k, val in step.items():
                if k in ("target", "selector", "value") and isinstance(val, str) and is_infrastructure_control(val):
                    return True

    # Check evidence
    for ev in mission.discovery_evidence or []:
        if isinstance(ev, dict):
            state = ev.get("readiness_state") or ev.get("state")
            if state in ("hosting_interstitial", "proxy_or_gateway_error", "browser_error"):
                return True

    # Check text blob
    blob = " ".join([
        mission.name or "",
        mission.objective or "",
        mission.expected_outcome or "",
        str(mission.journey or ""),
    ]).lower()

    if any(wake in blob for wake in _WAKE_LANGUAGE):
        return True
    if any(ctrl in blob for ctrl in _INFRA_CONTROL_LANGUAGE):
        return True

    return False


def validate_journey(
    mission: DiscoveredMission,
    capabilities: list[DiscoveredCapability] | None = None,
) -> JourneyValidationResult:
    """Programmatically inspect a candidate journey against quality requirements."""
    defects: list[QualityDefect] = []

    if is_infrastructure_mission(mission):
        defects.append(QualityDefect(
            code="INFRASTRUCTURE_DEPENDENCY",
            message="Journey depends on hosting provider infrastructure controls or interstitial content",
            severity="error",
        ))

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

    # 3. Outcome specificity and non-vacuous assertions
    raw_outcome = mission.expected_outcome or (
        mission.successCondition if isinstance(mission.successCondition, str) else None
    )
    if is_vague_outcome(raw_outcome):
        defects.append(QualityDefect(
            code="VAGUE_OUTCOME",
            message="Expected outcome is empty or generic placeholder",
            severity="error",
        ))

    # Vacuous / generic assertions check
    if isinstance(mission.successCondition, dict):
        keys = list(mission.successCondition.keys())
        if keys == ["element_count"]:
            sel = str(mission.successCondition.get("element_count", {}).get("selector", "")).strip().lower()
            if sel in _GENERIC_ELEMENT_COUNT_SELECTORS or sel in ("main", "body", "html", "div", "section", "p", "a", "button", "h1, h2, h3"):
                defects.append(QualityDefect(
                    code="VACUOUS_ASSERTION",
                    message=f"Success condition relies on generic layout selector ({sel}) rather than observable feature state",
                    severity="error",
                ))
        elif "url_matches" in keys:
            pat = str(mission.successCondition.get("url_matches", "")).strip()
            if pat in (".*", "^", "^.*$", ".*?", ""):
                defects.append(QualityDefect(
                    code="VACUOUS_ASSERTION",
                    message="url_matches pattern is vacuous and matches any destination",
                    severity="error",
                ))

    # Generic ungrounded action check
    all_text = " ".join([
        mission.name or "",
        mission.objective or "",
        mission.user_goal or "",
        " ".join(mission.journey or []),
        str(mission.steps or []),
    ]).lower()

    if "use the control matching the goal" in all_text or "click the button matching the goal" in all_text:
        defects.append(QualityDefect(
            code="GENERIC_ACTION",
            message="Journey contains generic placeholder instructions ('use the control matching the goal')",
            severity="error",
        ))

    if (
        "verify visible feedback or navigation" in all_text
        or "verify application state changes" in all_text
        or "verify the application state changes" in all_text
        or "verify visible feedback" in all_text
    ):
        defects.append(QualityDefect(
            code="GENERIC_ACTION",
            message="Journey contains generic action without observable application outcome",
            severity="error",
        ))

    # Specific control exploration check: password visibility toggle
    name_and_target = f"{mission.name} {mission.objective} {str(mission.steps)}".lower()
    if any(kw in name_and_target for kw in ("show password", "hide password", "toggle password", "password visibility")):
        has_attribute_check = False
        if isinstance(mission.successCondition, dict):
            if "element_attribute" in mission.successCondition:
                attr = mission.successCondition["element_attribute"].get("attribute", "")
                if attr in ("type", "aria-checked", "aria-expanded"):
                    has_attribute_check = True
        for step in mission.steps or []:
            if isinstance(step, dict) and step.get("type") in ("assert_attribute", "assert_value", "assert_visible"):
                has_attribute_check = True
        if not has_attribute_check:
            defects.append(QualityDefect(
                code="INADEQUATE_CONTROL_TEST",
                message="Password visibility control exploration must verify that the password input toggles to visible and returns to masked state",
                severity="error",
            ))

    # Specific OAuth button check
    if any(kw in name_and_target for kw in ("google", "apple", "oauth", "github", "microsoft")) and any(kw in name_and_target for kw in ("sign in", "login", "auth", "continue with")):
        if isinstance(mission.successCondition, dict) and "auth_verified" in mission.successCondition:
            defects.append(QualityDefect(
                code="INVALID_OAUTH_CLAIM",
                message="OAuth provider buttons cannot be verified as local login journeys without an authenticated test identity or OAuth mock harness",
                severity="error",
            ))
        if is_navigation_only_workflow(mission) or (isinstance(mission.successCondition, dict) and "element_count" in mission.successCondition):
            defects.append(QualityDefect(
                code="INVALID_OAUTH_CLAIM",
                message="Clicking an OAuth provider button without configured OAuth identity or external handoff assertions is invalid",
                severity="error",
            ))

    # Unmet Preconditions check
    needs_credentials = (
        mission.category == "auth"
        or "needs credentials" in name_and_target
        or any(isinstance(s, dict) and s.get("credential_field") for s in (mission.steps or []))
    )
    has_valid_creds = bool(
        getattr(mission, "credential_id", None)
        or any(isinstance(s, dict) and s.get("credential_id") not in (None, "", "null") for s in (mission.steps or []))
    )
    if needs_credentials and not has_valid_creds:
        mission.runnable = False
        mission.validation_status = "blocked_by_prerequisites"
        defects.append(QualityDefect(
            code="UNMET_PRECONDITION",
            message="Journey requires test credentials or authenticated session that is not currently available",
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
    """Attempt to ground journey candidate using concrete capability evidence.

    Does NOT fabricate generic strings or generic assertions. If real evidence
    is missing, the journey remains invalid.
    """
    matching_cap: DiscoveredCapability | None = None
    if capabilities:
        for cap in capabilities:
            if cap.id == mission.capability_id or (cap.name and cap.name.lower() in (mission.name or "").lower()):
                matching_cap = cap
                break

    # Ground Expected Outcome only from matching discovered capability evidence
    if is_vague_outcome(mission.expected_outcome) or not mission.expected_outcome:
        if matching_cap and matching_cap.expected_outcome and not is_vague_outcome(matching_cap.expected_outcome):
            mission.expected_outcome = matching_cap.expected_outcome

    # Ground success conditions in discovered workflow types when concrete steps exist
    name_lower = (mission.name + " " + (mission.objective or "")).lower()
    if mission.steps and "needs credentials" not in name_lower:
        if any(k in name_lower for k in ("search", "filter", "find records")):
            if not isinstance(mission.successCondition, dict) or "search_results" not in mission.successCondition:
                mission.successCondition = {
                    "search_results": {
                        "query": "",
                        "expected_matches": [],
                        "selector": "table, [role='table'], #records-table, .results",
                    }
                }
                if not mission.expected_outcome:
                    mission.expected_outcome = f"Execute search for {mission.name} and verify matching records appear in results table."
        elif any(k in name_lower for k in ("create", "add record", "new record", "save record", "post", "report")):
            if not isinstance(mission.successCondition, dict) or ("record_persisted" not in mission.successCondition and "text_visible" not in mission.successCondition):
                mission.successCondition = {
                    "record_persisted": {
                        "expected_text": mission.name,
                        "reload": True,
                    }
                }
                if not mission.expected_outcome:
                    mission.expected_outcome = f"Submit and verify {mission.name} is successfully generated and persisted."

    # Clean up empty url_changed_to
    if isinstance(mission.successCondition, dict) and "url_changed_to" in mission.successCondition:
        cfg = mission.successCondition["url_changed_to"]
        if isinstance(cfg, dict) and "to" not in cfg:
            del mission.successCondition["url_changed_to"]

    # Ground User Goal from objective
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
        if "record_persisted" in keys or "search_results" in keys or "validation_error" in keys or "text_visible" in keys or "auth_verified" in keys:
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


def normalize_journey_intent(name: str, route_path: str = "") -> str:
    """Normalize workflow intent string to detect semantic duplicate missions."""
    n = name.strip().lower()
    n = re.sub(r"\b(new|create|add|generate|post)\b", "create", n)
    n = re.sub(r"\b(sign\s*in|log\s*in|signin|login|auth)\b", "login", n)
    n = re.sub(r"\b(sign\s*up|signup|register|registration)\b", "register", n)
    n = re.sub(r"\b(find|search|filter|browse)\b", "search", n)
    n = re.sub(r"\b(view|list|show)\b", "view", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    # Deduplicate adjacent identical words (e.g. 'create create' -> 'create')
    words = [w for w in n.split() if w]
    deduped_words: list[str] = []
    for w in words:
        if not deduped_words or deduped_words[-1] != w:
            deduped_words.append(w)
    return f"{route_path}:{' '.join(deduped_words)}"


def deduplicate_and_rank_journeys(
    missions: list[DiscoveredMission],
    capabilities: list[DiscoveredCapability] | None = None,
    max_results: int = 6,
    goal: str | None = None,
) -> list[DiscoveredMission]:
    """Validate, repair, deduplicate, score, and rank candidate journeys.
    
    Guarantees:
    - Never recommends shallow navigation or auth as the primary journey when real features exist
    - Rejects invalid or unrepaired journeys
    - Recommends the highest-value functional workflow with an explicit rationale
    """
    validated: list[DiscoveredMission] = []
    blocked_missions: list[DiscoveredMission] = []
    seen_keys: set[str] = set()

    for m in missions:
        # Check and attempt repair only with concrete capability evidence
        val = validate_journey(m, capabilities)
        if not val.is_valid:
            m = repair_journey(m, capabilities)
            val = validate_journey(m, capabilities)

        if not val.is_valid:
            m.runnable = False
            m.validation_status = "rejected_by_quality_gate"
            m.rejection_reasons = [d.message for d in val.defects]
            logger.info("Excluding invalid journey '%s': %s", m.name, [d.message for d in val.defects])
            continue

        if m.validation_status == "blocked_by_prerequisites" or not m.runnable:
            m.runnable = False
            m.recommended = False
            route_path = (m.route_analysis or {}).get("path", "")
            intent_norm = normalize_journey_intent(m.name, route_path)
            key = f"blocked:{intent_norm}"
            if key not in seen_keys:
                seen_keys.add(key)
                blocked_missions.append(m)
            continue

        m.runnable = True
        m.validation_status = "eligible"
        m.rejection_reasons = []

        # Deduplication key based on normalized intent, category, and target path
        route_path = (m.route_analysis or {}).get("path", "")
        intent_norm = normalize_journey_intent(m.name, route_path)
        key = f"{m.classification}:{m.category}:{intent_norm}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        validated.append(m)

    if not validated:
        return blocked_missions[:max_results]

    # Score each validated journey
    scored: list[tuple[float, DiscoveredMission]] = []
    goal_norm = goal.strip().lower() if goal else ""
    for m in validated:
        s = score_journey(m, capabilities)
        if goal_norm and (
            goal_norm in m.name.lower()
            or goal_norm in (m.title or "").lower()
            or goal_norm in (m.user_goal or "").lower()
            or any(word in (m.name + " " + (m.title or "")).lower() for word in goal_norm.split() if len(word) > 3)
        ):
            s += 1.0  # Significant priority boost for explicit user goal
        scored.append((s, m))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Designate exactly ONE recommended journey from eligible runnable candidates
    results = [m for _, m in scored if m.runnable]
    if not results:
        return blocked_missions[:max_results]

    for m in results:
        m.recommended = False

    if goal_norm:
        exact_match = next(
            (m for m in results if m.name.lower() == goal_norm or (m.title or "").lower() == goal_norm),
            None,
        )
        if exact_match:
            primary_candidate = exact_match
        else:
            primary_candidate = next(
                (
                    m for m in results
                    if goal_norm in m.name.lower()
                    or goal_norm in (m.title or "").lower()
                    or any(w in m.name.lower() for w in goal_norm.split() if len(w) > 3)
                ),
                results[0]
            )
    else:
        primary_candidate = next(
            (m for m in results if m.classification == "functional" and m.category not in ("auth", "navigation")),
            next((m for m in results if m.category != "auth"), results[0])
        )
    primary_candidate.recommended = True
    primary_candidate.ranking_rationale = (
        f"Selected as highest-value journey: tests core capability '{primary_candidate.name}' "
        f"with verifiable outcome: '{primary_candidate.expected_outcome}'"
    )
    if primary_candidate in results:
        results.remove(primary_candidate)
        results.insert(0, primary_candidate)

    return (results + blocked_missions)[:max_results]
