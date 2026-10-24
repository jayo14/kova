from __future__ import annotations

import logging
import uuid
from typing import Any

from app.modules.flows.schemas import StateAssertion, StateMutation
from app.modules.product_graph.schemas import Action, Capability, Page, State

logger = logging.getLogger(__name__)


def infer_effect_from_label(
    text: str, tag: str, page_pattern: str
) -> tuple[list[StateAssertion], list[str], float, str]:
    """Infer expected effect, mutated keys, confidence, and source from element text and tag."""
    t = text.strip().lower()

    if any(k in t for k in ("enroll", "join course", "take course")):
        return [StateAssertion(key="enrolled", value=True, predicate="eq")], ["enrolled"], 0.65, "heuristic"
    if any(k in t for k in ("log in", "login", "sign in", "signin")):
        return [StateAssertion(key="authenticated", value=True, predicate="eq")], ["authenticated"], 0.85, "discovered"
    if any(k in t for k in ("log out", "logout", "sign out", "signout")):
        return [StateAssertion(key="authenticated", value=False, predicate="eq")], ["authenticated"], 0.85, "discovered"
    if any(k in t for k in ("add to cart", "buy now", "purchase")):
        return [StateAssertion(key="cart_updated", value=True, predicate="eq")], ["cart"], 0.7, "heuristic"
    if any(k in t for k in ("delete", "remove", "cancel")):
        return [StateAssertion(key="deleted", value=True, predicate="eq")], ["deleted"], 0.55, "heuristic"
    if any(k in t for k in ("save", "submit", "update", "send", "post", "confirm")):
        key = "saved"
        if "contact" in page_pattern:
            key = "contact_form_submitted"
        elif "profile" in page_pattern:
            key = "profile_updated"
        return [StateAssertion(key=key, value=True, predicate="eq")], [key], 0.6, "heuristic"

    # Default fallback
    return [], [], 0.4, "heuristic"


class CapabilityExtractor:
    def __init__(self, project_id: uuid.UUID):
        self.project_id = project_id

    async def extract_actions_and_capabilities(
        self,
        browser_page: Any,
        page_obj: Page,
    ) -> tuple[list[Action], list[Capability], list[State]]:
        """Extract interactive elements on a page and group them into capabilities and states."""
        actions: list[Action] = []
        capabilities: list[Capability] = []
        states: list[State] = []

        try:
            elements: list[dict[str, Any]] = await browser_page.evaluate("""
                () => {
                    const items = [];
                    const selectors = 'button, input[type="submit"], input[type="button"], a[role="button"], [role="button"], input:not([type="hidden"]), textarea, select, a[href]';
                    document.querySelectorAll(selectors).forEach((el, idx) => {
                        // Check visibility
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) return;

                        let text = (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();
                        let tag = el.tagName.toLowerCase();
                        let type = el.getAttribute('type') || (tag === 'textarea' ? 'textarea' : (tag === 'select' ? 'select' : 'button'));
                        let id = el.id ? '#' + el.id : '';
                        let name = el.getAttribute('name');
                        let testId = el.getAttribute('data-testid');

                        let selector = '';
                        if (testId) selector = `[data-testid="${testId}"]`;
                        else if (id) selector = id;
                        else if (name) selector = `${tag}[name="${name}"]`;
                        else if (text && text.length < 50) selector = `${tag}:has-text("${text.replace(/"/g, '\\\\"')}")`;
                        else selector = `${tag}:nth-of-type(${idx + 1})`;

                        items.push({
                            text: text || `${tag}_${idx}`,
                            tag: tag,
                            type: type,
                            selector: selector,
                        });
                    });
                    return items;
                }
            """)

            for el in elements:
                effect, mutates, confidence, source = infer_effect_from_label(
                    el["text"], el["tag"], page_obj.url_pattern
                )

                if el["tag"] in ("input", "textarea", "select") and el["type"] not in ("submit", "button", "reset"):
                    act_type = "input"
                elif el["type"] == "submit":
                    act_type = "submit"
                else:
                    act_type = "click"
                action_name = el["text"][:80] if el["text"] else f"{act_type.capitalize()} on {page_obj.url_pattern}"

                action = Action(
                    project_id=self.project_id,
                    page_id=page_obj.id,
                    name=action_name,
                    selector=el["selector"],
                    action_type=act_type,
                    expected_effect=effect,
                    mutates=mutates,
                    source=source,
                    confidence=confidence,
                )
                actions.append(action)

                # Collect states from effects
                for eff in effect:
                    states.append(
                        State(
                            project_id=self.project_id,
                            key=eff.key,
                            value_type="bool",
                            default_value=False,
                            description=f"State associated with action '{action_name}'",
                        )
                    )

            # Group discovered actions into capabilities
            effect_keys = {k for a in actions for k in a.mutates}
            if "enrolled" in effect_keys:
                capabilities.append(
                    Capability(
                        project_id=self.project_id,
                        name="course_enrollment",
                        description="Ability to enroll in courses",
                        produces_state=[StateMutation(key="enrolled", action="set", value=True)],
                        kind="primary",
                        source_files=page_obj.source_files or [],
                        source="heuristic",
                        confidence=0.7,
                    )
                )
            if "authenticated" in effect_keys:
                capabilities.append(
                    Capability(
                        project_id=self.project_id,
                        name="authentication",
                        description="Ability to authenticate and establish user session",
                        produces_state=[StateMutation(key="authenticated", action="set", value=True)],
                        kind="setup",
                        source_files=page_obj.source_files or [],
                        source="discovered",
                        confidence=0.9,
                    )
                )
            if any(k in effect_keys for k in ("saved", "profile_updated", "contact_form_submitted")):
                state_mutations = [StateMutation(key="form_submitted", action="set", value=True)]
                for k in ("saved", "profile_updated", "contact_form_submitted"):
                    if k in effect_keys:
                        state_mutations.append(StateMutation(key=k, action="set", value=True))
                capabilities.append(
                    Capability(
                        project_id=self.project_id,
                        name="data_submission",
                        description=f"Form submission capability on {page_obj.url_pattern}",
                        produces_state=state_mutations,
                        kind="primary",
                        source_files=page_obj.source_files or [],
                        source="heuristic",
                        confidence=0.6,
                    )
                )

        except Exception as e:
            logger.warning("Action extraction failed for %s: %s", page_obj.url_pattern, e)

        return actions, capabilities, states
