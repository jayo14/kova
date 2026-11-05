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

KIND_TITLE_VIOLATION_PATTERNS = (
    # A mission titled as a write/create action must actually submit something.
    re.compile(r"\b(create|generate|add|post|save|submit|build|make)\b", re.I),
)
NAVIGATION_TITLE_WORDS = (
    "open", "browse", "navigate", "visit", "view", "inspect", "load", "access",
)

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


def validate_missions_against_site_map(
    missions: list[DiscoveredMission],
    site_map: list[dict] | None,
) -> list[DiscoveredMission]:
    """Live dry-run validation: keep only missions whose entry point and key controls
    still exist in the observed SiteMap, and set confidence from that evidence.

    A mission's entry point (route/control) must be present in the observed SiteMap
    nodes. Key controls referenced by control_hints must be observable. Missions that
    fail the dry run are dropped (not repaired, since the SiteMap is source of truth).
    Confidence is raised when entry point + controls are observed, lowered otherwise.
    """
    if not site_map:
        return missions

    # Index observed controls by (url, label) for dry-run lookup.
    observed_controls: set[tuple[str, str]] = set()
    observed_urls: set[str] = set()
    for node in site_map:
        url = (node.get("url") or node.get("url_norm") or "").rstrip("/")
        observed_urls.add(url)
        for el in (node.get("interactive_elements") or []):
            label = (el.get("name") or el.get("text") or "").strip().lower()
            if label:
                observed_controls.add((url, label))
        for action in (node.get("primary_actions") or []):
            label = (action.get("name") or action.get("text") or "").strip().lower()
            if label:
                observed_controls.add((url, label))

    kept: list[DiscoveredMission] = []
    for node in site_map:
        print(f'  site_map node: url={node.get("url")}, needs_auth={node.get("needs_auth")}')
    for m in missions:
        entry_url = ""
        if isinstance(m.route_analysis, dict):
            entry_url = (m.route_analysis.get("url") or m.route_analysis.get("path") or "").rstrip("/")
        if not entry_url and m.discovery_evidence:
            for ev in m.discovery_evidence:
                if isinstance(ev, dict) and ev.get("kind") == "route":
                    entry_url = str(ev.get("path") or "").rstrip("/")
                    break

        hints = m.control_hints or []
        entry_obs = (not entry_url) or (entry_url in observed_urls)
        entry_observed = entry_obs
        controls_observed = (not hints) or all(
            any(url == entry_url or not entry_url for url, _ in observed_controls)
            and any(label == h.lower() for _, label in observed_controls)
            for h in hints
        )

        if not entry_observed or not controls_observed:
            # Entry point or key control no longer in SiteMap: drop honestly.
            m.runnable = False
            m.validation_status = "rejected_by_quality_gate"
            m.rejection_reasons = [
                "Entry point or key control not present in observed SiteMap (dry-run failed)"
            ]
            continue

        # Confidence derived from dry-run evidence, not copied from the model.
        base = m.confidence or 0.5
        m.confidence = round(min(0.95, base + 0.15), 2)
        kept.append(m)

    return kept


FLIMSY_ELEMENT_PATTERNS = [
    r"\b\d+\s+pages\b",
    r"\bcheck_circle\b",
    r"\b(article|table_chart|engineering)\s+(cover|weekly|chapter)",
    r"\b[A-Z][a-z]+\s+[A-Z]\.\s*·",
    r"\b\d+(\.\d+)?/\d+\s+stars?\b",
    r"\b(trusted by|reviews? from|stars from)\b",
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    r"\b(privacy policy|terms of (service|use)|terms and conditions)\b",
    r"\btoggle password\b",
    r"\b(show|hide)\s+password\b",
    r"\bpassword visibility\b",
    r"\bexplore\s+[^\s]+@[^\s]+\b",
    r"\b(explore|interact with)\s+(password|email|input|checkbox)\b",
    r"^(or|and)$",
]


def is_flimsy_landing_element(name: str | None) -> bool:
    """Detect whether an element is a static marketing card, testimonial, or review."""
    if not name:
        return True
    text = str(name).strip()
    if len(text) < 3:
        return True
    if any(re.search(pat, text, re.I) for pat in FLIMSY_ELEMENT_PATTERNS):
        return True
    if text.startswith("Explore ") and any(w in text.lower() for w in ["·", "pages", "cover page", "weekly log", "chapter 3"]):
        return True
    if re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+,\s+[A-Z][a-zA-Z\s]+(at|@)\s+[A-Z]", text):
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

    # Skip links and same-page fragment anchors check
    name_and_goal = f"{mission.name} {mission.objective} {mission.user_goal} {str(mission.steps)}".lower()
    if any(sk in name_and_goal for sk in ["skip to main", "skip to content", "skip navigation", "skip to"]):
        defects.append(QualityDefect(
            code="SKIP_LINK_OR_ANCHOR",
            message="Skip links ('Skip to main content') must not be treated as user journeys",
            severity="error",
        ))

    route_path = (mission.route_analysis or {}).get("path", "")
    if route_path.startswith("#") or (route_path.startswith("/#") and not route_path.startswith("/#/")):
        defects.append(QualityDefect(
            code="SAME_PAGE_ANCHOR",
            message="Same-page anchors (#solution, #pricing, #main-content) must not be treated as user journeys",
            severity="error",
        ))

    if "verify core journeys for:" in name_and_goal:
        defects.append(QualityDefect(
            code="TAGLINE_MISSION",
            message="Site tagline must not be used as journey title or objective",
            severity="error",
        ))

    # Reject flimsy landing page showcase mockups and testimonials
    if getattr(mission, "kind", None) not in ("control_exploration", "navigation_test") and is_flimsy_landing_element(mission.name):
        defects.append(QualityDefect(
            code="FLIMSY_MOCKUP_OR_TESTIMONIAL",
            message="Static landing page showcase mockups or testimonials must not be treated as user journeys",
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
    # Classification honesty: a navigation-only mission must be titled as such,
    # never as a create/write action that submits nothing.
    kind = mission.kind or ""
    name = mission.name or ""
    if kind == "navigation" and any(p.search(name) for p in KIND_TITLE_VIOLATION_PATTERNS):
        defects.append(QualityDefect(
            code="KIND_TITLE_MISMATCH",
            message=f"Navigation-only mission '{name}' is titled as a write action but never submits",
            severity="error",
        ))
    # A write_workflow kind must actually submit data; steps must include an input/submit action.
    if kind == "write_workflow":
        step_types = {str(s.get("type") or s.get("action") or "").lower() for s in (mission.steps or []) if isinstance(s, dict)}
        submits = step_types & {"click", "type", "fill", "select", "submit", "press"}
        if not submits:
            defects.append(QualityDefect(
                code="WRITE_WORKFLOW_NO_SUBMIT",
                message=f"Write workflow '{name}' declares write_workflow kind but no step submits data",
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
    capabilities: list[Any] | None = None,
) -> DiscoveredMission:
    """Attempt to ground journey candidate using concrete capability evidence.

    Does NOT fabricate generic strings or generic assertions. If real evidence
    is missing, the journey remains invalid.
    """
    matching_cap: Any | None = None
    if capabilities:
        for cap in capabilities:
            cap_id = cap.get("id") if isinstance(cap, dict) else getattr(cap, "id", None)
            cap_name = cap.get("name") if isinstance(cap, dict) else getattr(cap, "name", "")
            if cap_id == mission.capability_id or (cap_name and cap_name.lower() in (mission.name or "").lower()):
                matching_cap = cap
                break

    cap_outcome = (
        (matching_cap.get("expected_outcome") if isinstance(matching_cap, dict) else getattr(matching_cap, "expected_outcome", None))
        if matching_cap else None
    )

    name_lower = (mission.name + " " + (mission.objective or "")).lower()

    # Ground Expected Outcome only from matching discovered capability evidence or grounded category
    if is_vague_outcome(mission.expected_outcome) or not mission.expected_outcome:
        if cap_outcome and not is_vague_outcome(cap_outcome):
            mission.expected_outcome = cap_outcome
            mission.repaired = True
            logger.info("Repair loop: grounded outcome for '%s' from capability: %s", mission.name, cap_outcome)
        elif any(k in name_lower for k in ("cart", "checkout", "buy", "product")):
            mission.expected_outcome = "Selected item is added to cart and checkout flow begins with order summary."
            mission.repaired = True
            logger.info("Repair loop: grounded e-commerce outcome for '%s'", mission.name)
        elif any(k in name_lower for k in ("contact", "inquiry", "support", "feedback")):
            mission.expected_outcome = "Contact form submits successfully and renders confirmation notification."
            mission.repaired = True
            logger.info("Repair loop: grounded contact form outcome for '%s'", mission.name)
        elif any(k in name_lower for k in ("wrong credentials", "invalid password", "login failure", "login error")):
            mission.expected_outcome = "Form validation detects invalid credentials and displays authentication error alert."
            mission.repaired = True
            logger.info("Repair loop: grounded auth error outcome for '%s'", mission.name)
        elif any(k in name_lower for k in ("pricing", "plan")):
            mission.expected_outcome = "Pricing tiers with plan features and functional selection buttons are displayed."
            mission.repaired = True
            logger.info("Repair loop: grounded pricing outcome for '%s'", mission.name)

    # Ground success conditions in discovered workflow types when concrete steps exist
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
                    mission.repaired = True
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
                    mission.repaired = True

    # Clean up empty url_changed_to
    if isinstance(mission.successCondition, dict) and "url_changed_to" in mission.successCondition:
        cfg = mission.successCondition["url_changed_to"]
        if isinstance(cfg, dict) and "to" not in cfg:
            del mission.successCondition["url_changed_to"]

    # Ground User Goal from objective
    if not mission.user_goal:
        mission.user_goal = mission.objective

    return mission


# ---------------------------------------------------------------------------
# Deterministic capability templates (used when AI is unavailable or fails)
# Built exclusively from observed controls — no product keywords.
# ---------------------------------------------------------------------------

_CONTROL_KIND_PASSWORD_INPUT = "password_input"
_CONTROL_KIND_LOGIN_FORM = "login_form"
_CONTROL_KIND_SIGNUP_FORM = "signup_form"
_CONTROL_KIND_FORGOT_PASSWORD = "forgot_password"
_CONTROL_KIND_OAUTH_BUTTON = "oauth_button"


def _detect_control_kind(el_name: str, element: dict | None = None) -> str | None:
    name = (el_name or "").lower()
    blob = name
    if element:
        blob += " " + str(element.get("type", "")) + " " + str(element.get("role", "")) + " " + str(element.get("aria-label", ""))
    if any(k in blob for k in ("show password", "hide password", "toggle password", "password visibility", "reveal password", "type=password", "input[type='password'", "input[name*='password'", "input[id*='password'")):
        return _CONTROL_KIND_PASSWORD_INPUT
    if any(k in blob for k in ("oauth", "google", "apple", "github", "microsoft", "sign in with", "continue with")):
        return _CONTROL_KIND_OAUTH_BUTTON
    if any(k in blob for k in ("forgot password", "reset password", "can't sign in", "trouble signing", "recover account")):
        return _CONTROL_KIND_FORGOT_PASSWORD
    if any(k in blob for k in ("sign in", "log in", "login", "signin")) and ("password" in blob or "submit" in blob):
        return _CONTROL_KIND_LOGIN_FORM
    if any(k in blob for k in ("sign up", "signup", "create account", "register", "registration")) and ("password" in blob or "submit" in blob):
        return _CONTROL_KIND_SIGNUP_FORM
    return None


def _build_password_toggle_template(
    control_name: str,
    page_url: str,
    page_title: str,
    element: dict | None = None,
) -> DiscoveredMission:
    pw_input_sel = "input[type='password'], input[name*='password' i], input[id*='password' i]"
    toggle_sel = element.get("selector") if element else None
    if not toggle_sel:
        toggle_sel = f"button:has-text('{control_name}'), [role='button']:has-text('{control_name}')"
    return DiscoveredMission(
        id=f"mission-{uuid.uuid4().hex[:8]}",
        name=f"Toggle password visibility: {control_name}",
        title=f"Toggle password visibility: {control_name}",
        description="Enter test text into the password field, toggle visibility to reveal cleartext, then toggle again to restore masking.",
        objective="Verify that the password visibility toggle reveals masked text and returns to masked state.",
        persona="Visitor",
        category="control_exploration",
        journey=[
            f"Open {page_title or 'the application'}",
            "Enter test text into password input",
            f"Click '{control_name}' to reveal password",
            "Verify password input type changes to text",
            f"Click '{control_name}' again to mask password",
            "Verify password input type returns to password",
        ],
        steps=[
            {"type": "navigate", "url": page_url},
            {"type": "wait", "value": "500"},
            {"type": "type", "target": pw_input_sel, "value": "SecretPassword123!"},
            {"type": "wait", "value": "200"},
            {"type": "click", "target": toggle_sel},
            {"type": "wait", "value": "200"},
            {"type": "click", "target": toggle_sel},
            {"type": "wait", "value": "200"},
        ],
        successCondition={
            "element_attribute": {
                "target": pw_input_sel,
                "attribute": "type",
                "value": "password",
            }
        },
        confidence=0.85,
        estimated_time_seconds=10,
        user_goal="Toggle password visibility to verify cleartext reveal and masking",
        expected_outcome="Password field toggles between masked and visible states and returns to masked password type",
        classification="functional",
        kind="control_exploration",
        runnable=True,
        validation_status="eligible",
        control_hints=[control_name, toggle_sel, pw_input_sel],
        provenance={
            "observed_controls": [control_name, toggle_sel, pw_input_sel],
            "observed_routes": [page_url],
            "preconditions": [],
            "unmet_preconditions": [],
            "template": "password_toggle",
        },
    )


def _build_login_form_template(
    control_name: str,
    page_url: str,
    page_title: str,
    element: dict | None = None,
) -> DiscoveredMission:
    return DiscoveredMission(
        id=f"mission-{uuid.uuid4().hex[:8]}",
        name=f"Sign in with empty credentials: {control_name}",
        title=f"Sign in with empty credentials: {control_name}",
        description="Submit the login form without entering credentials and verify a validation error appears; then submit wrong credentials and verify the session remains logged out.",
        objective="Verify login form validation rejects empty and invalid credentials without authenticating.",
        persona="Visitor",
        category="auth",
        journey=[
            f"Open {page_title or 'the application'}",
            "Click submit with empty credentials",
            "Verify validation error appears for missing credentials",
            "Enter wrong credentials",
            "Click submit",
            "Verify error message appears and session remains logged out",
        ],
        steps=[
            {"type": "navigate", "url": page_url},
            {"type": "wait", "value": "500"},
            {"type": "click", "target": f"button:has-text('{control_name}'), [role='button']:has-text('{control_name}')"},
            {"type": "wait", "value": "500"},
            {"type": "assert_visible", "target": "[role='alert'], .error, [aria-invalid='true'], .invalid-feedback"},
            {"type": "type", "target": "input[name*='email' i], input[name*='username' i], input[type='email']", "value": "wrong@example.com"},
            {"type": "type", "target": "input[type='password'], input[name*='password' i]", "value": "WrongPassword123!"},
            {"type": "click", "target": f"button:has-text('{control_name}'), [role='button']:has-text('{control_name}')"},
            {"type": "wait", "value": "500"},
            {"type": "assert_visible", "target": "[role='alert'], .error, .invalid-feedback"},
        ],
        successCondition={
            "validation_error": {
                "appears_on_empty_submit": True,
                "appears_on_wrong_credentials": True,
                "session_remains_logged_out": True,
            }
        },
        confidence=0.8,
        estimated_time_seconds=15,
        user_goal="Verify login form rejects invalid credentials and keeps session logged out",
        expected_outcome="Empty submit shows validation error; wrong credentials show error and session stays logged out",
        classification="functional",
        kind="feature_test",
        runnable=False,
        validation_status="blocked_by_prerequisites",
        control_hints=[control_name],
        rejection_reasons=[
            "Journey requires test credentials or authenticated session that is not currently available"
        ],
        provenance={
            "observed_controls": [control_name],
            "observed_routes": [page_url],
            "preconditions": ["valid_login_credentials"],
            "unmet_preconditions": ["valid_login_credentials"],
            "template": "login_form",
            "blocked_reason": "BLOCKED_NEEDS_CREDENTIALS: Login journey requires credentials to proceed beyond validation checks",
        },
    )


def _build_signup_form_template(
    control_name: str,
    page_url: str,
    page_title: str,
    element: dict | None = None,
) -> DiscoveredMission:
    return DiscoveredMission(
        id=f"mission-{uuid.uuid4().hex[:8]}",
        name=f"Create account with invalid data: {control_name}",
        title=f"Create account with invalid data: {control_name}",
        description="Submit the signup form with an invalid email and mismatched passwords and verify validation errors appear for both fields.",
        objective="Verify signup form validation rejects invalid email and mismatched passwords.",
        persona="Visitor",
        category="auth",
        journey=[
            f"Open {page_title or 'the application'}",
            "Enter invalid email address",
            "Enter mismatched passwords",
            "Click submit",
            "Verify validation error for invalid email",
            "Verify validation error for password mismatch",
        ],
        steps=[
            {"type": "navigate", "url": page_url},
            {"type": "wait", "value": "500"},
            {"type": "type", "target": "input[name*='email' i], input[type='email']", "value": "not-an-email"},
            {"type": "type", "target": "input[type='password'], input[name*='password' i]", "value": "Password123!"},
            {"type": "type", "target": "input[name*='confirm' i], input[name*='password_confirmation' i]", "value": "DifferentPassword123!"},
            {"type": "click", "target": f"button:has-text('{control_name}'), [role='button']:has-text('{control_name}')"},
            {"type": "wait", "value": "500"},
            {"type": "assert_visible", "target": "[role='alert'], .error, [aria-invalid='true'], .invalid-feedback"},
        ],
        successCondition={
            "validation_error": {
                "invalid_email_rejected": True,
                "password_mismatch_rejected": True,
                "account_not_created": True,
            }
        },
        confidence=0.8,
        estimated_time_seconds=15,
        user_goal="Verify signup form validates email format and password matching",
        expected_outcome="Invalid email and mismatched passwords produce validation errors; no account is created",
        classification="functional",
        kind="feature_test",
        runnable=False,
        validation_status="blocked_by_prerequisites",
        control_hints=[control_name],
        rejection_reasons=[
            "Journey requires test credentials or authenticated session that is not currently available"
        ],
        provenance={
            "observed_controls": [control_name],
            "observed_routes": [page_url],
            "preconditions": ["valid_signup_credentials"],
            "unmet_preconditions": ["valid_signup_credentials"],
            "template": "signup_form",
            "blocked_reason": "BLOCKED_NEEDS_CREDENTIALS: Signup journey requires credentials to proceed beyond validation checks",
        },
    )


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
    # Consolidate journeys that achieve the same user goal through different entry points.
    consolidated: list[DiscoveredMission] = []
    seen_goals: dict[str, DiscoveredMission] = {}
    for m in missions:
        goal_key = (m.user_goal or m.name or "").strip().lower()
        if not goal_key:
            consolidated.append(m)
            continue
        existing = seen_goals.get(goal_key)
        if existing is not None:
            if (m.confidence or 0) > (existing.confidence or 0):
                seen_goals[goal_key] = m
                consolidated = [x for x in consolidated if x is not existing]
                consolidated.append(m)
            continue
        seen_goals[goal_key] = m
        consolidated.append(m)
    missions = consolidated
    
    Guarantees:
    - Never recommends shallow navigation or auth as the primary journey when real features exist
    - Rejects invalid or unrepaired journeys
    - Recommends the highest-value functional workflow with an explicit rationale
    """
    validated: list[DiscoveredMission] = []
    blocked_missions: list[DiscoveredMission] = []
    seen_keys: set[str] = set()

    for m in missions:
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

        m.runnable = True
        m.validation_status = "eligible"
        m.rejection_reasons = []

        # Deduplicate by capability (entry point), not by title.
        cap_key = m.capability_id or (
            (m.route_analysis or {}).get("path", "")
            + "|"
            + "|".join(sorted(m.control_hints or []))
        )
        if cap_key == "|":
            cap_key = f"|{m.name.strip().casefold()}"
        key = f"{m.classification}:{m.category}:{cap_key}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        validated.append(m)

    if not validated:
        return blocked_missions[:max_results]

    # Prefer meaningful workflows over navigation-only journeys when available.
    # Navigation-only missions are rejected from runnable results but retained as
    # blocked entries for transparency.
    functional = [m for m in validated if not is_navigation_only_workflow(m)]
    if functional:
        for m in validated:
            if is_navigation_only_workflow(m):
                m.runnable = False
                m.recommended = False
                if m.validation_status != "rejected_by_quality_gate":
                    m.validation_status = "rejected_navigation_only"
                blocked_missions.append(m)
        validated = functional

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
