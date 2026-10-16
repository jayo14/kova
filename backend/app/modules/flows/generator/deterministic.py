import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flows.generator.representations import (
    step_assert,
    step_capture_evidence,
    step_click,
    step_input,
    step_locate,
    step_navigate,
    to_gherkin_representation,
    to_json_representation,
)
from app.modules.flows.generator.schemas import (
    ExecutionStep,
    GeneratedFlow,
    GenerationRequest,
)
from app.modules.flows.schemas import FlowStateContract, StateAssertion
from app.modules.product_graph.models import (
    ProductAction,
    ProductCapability,
    ProductGoal,
    ProductPage,
    ProductPersona,
)
from app.modules.product_graph.repository import ProductGraphRepository

logger = logging.getLogger(__name__)


class DeterministicFlowGenerator:
    """Deterministic generator that walks the Product Graph to produce executable flows."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProductGraphRepository(db)

    async def generate(
        self, request: GenerationRequest
    ) -> tuple[list[GeneratedFlow], list[str]]:
        """Walk the graph and generate flows.

        Returns (generated_flows, unresolved_goals).
        """
        flows: list[GeneratedFlow] = []
        unresolved: list[str] = []

        all_pages = await self.repo.list_pages_by_project(request.project_id)
        all_actions = await self.repo.list_actions_by_project(request.project_id)
        all_capabilities = await self.repo.list_capabilities_by_project(request.project_id)
        all_personas = await self.repo.list_personas_by_project(request.project_id)

        target_persona: ProductPersona | None = None
        if request.persona_id:
            target_persona = next((p for p in all_personas if p.id == request.persona_id), None)

        # 1. Handle target_capability
        if request.target_capability:
            cap = next(
                (c for c in all_capabilities if c.name == request.target_capability),
                None,
            )
            if cap:
                flow = await self._generate_flow_for_capability(
                    cap=cap,
                    all_pages=all_pages,
                    all_actions=all_actions,
                    all_capabilities=all_capabilities,
                    persona=target_persona,
                    goal=None,
                )
                if flow:
                    flows.append(flow)
                else:
                    unresolved.append(request.target_capability)
            else:
                unresolved.append(request.target_capability)

        # 2. Handle goal_id
        if request.goal_id:
            goal = await self.repo.get_goal(request.goal_id)
            if not goal:
                unresolved.append(str(request.goal_id))
            else:
                goal_persona = target_persona
                if not goal_persona and goal.persona_id:
                    goal_persona = next((p for p in all_personas if p.id == goal.persona_id), None)

                goal_flows = await self._generate_flows_for_goal(
                    goal=goal,
                    all_pages=all_pages,
                    all_actions=all_actions,
                    all_capabilities=all_capabilities,
                    persona=goal_persona,
                )
                if goal_flows:
                    flows.extend(goal_flows)
                else:
                    unresolved.append(goal.name)

        return flows, unresolved

    async def _generate_flows_for_goal(
        self,
        goal: ProductGoal,
        all_pages: list[ProductPage],
        all_actions: list[ProductAction],
        all_capabilities: list[ProductCapability],
        persona: ProductPersona | None,
    ) -> list[GeneratedFlow]:
        """Generate flows satisfying a goal's success criteria."""
        generated: list[GeneratedFlow] = []
        criteria = goal.success_criteria or []

        # Find capabilities that satisfy the criteria
        matching_caps: list[ProductCapability] = []
        for crit in criteria:
            crit_key = crit.get("key") if isinstance(crit, dict) else getattr(crit, "key", "")
            crit_val = crit.get("value") if isinstance(crit, dict) else getattr(crit, "value", None)

            # Match capability by produces_state
            for c in all_capabilities:
                if persona and persona.default_capabilities:
                    if c.name not in persona.default_capabilities and c.kind != "shared":
                        continue

                produces = c.produces_state or []
                matched = False
                for p in produces:
                    p_key = p.get("key") if isinstance(p, dict) else getattr(p, "key", "")
                    p_val = p.get("value") if isinstance(p, dict) else getattr(p, "value", None)
                    if p_key == crit_key and (crit_val is None or p_val == crit_val):
                        if c not in matching_caps:
                            matching_caps.append(c)
                        matched = True
                        break

                if not matched:
                    # Match by name or kind
                    c_name_norm = c.name.lower().replace("_", " ")
                    crit_words = crit_key.lower().replace("_", " ").split()
                    if any(w in c_name_norm for w in crit_words if len(w) > 3) or (
                        crit_key in ("authenticated", "signed_up") and (c.kind == "auth" or "auth" in c.name.lower())
                    ):
                        if c not in matching_caps:
                            matching_caps.append(c)

        # Match any capability whose name or key is mentioned in goal.name
        goal_lower = goal.name.lower()
        for c in all_capabilities:
            if c in matching_caps:
                continue
            c_name_norm = c.name.lower().replace("_", " ")
            if (
                c_name_norm in goal_lower
                or any(word in goal_lower for word in c_name_norm.split() if len(word) > 3)
                or (c.kind == "auth" and any(k in goal_lower for k in ("sign in", "login", "log in", "sign up", "signup", "auth")))
            ):
                matching_caps.append(c)

        for cap in matching_caps:
            flow = await self._generate_flow_for_capability(
                cap=cap,
                all_pages=all_pages,
                all_actions=all_actions,
                all_capabilities=all_capabilities,
                persona=persona,
                goal=goal,
            )
            if flow:
                generated.append(flow)

        return generated

    async def _generate_flow_for_capability(
        self,
        cap: ProductCapability,
        all_pages: list[ProductPage],
        all_actions: list[ProductAction],
        all_capabilities: list[ProductCapability],
        persona: ProductPersona | None,
        goal: ProductGoal | None,
    ) -> GeneratedFlow | None:
        """Construct an executable flow for a specific capability."""
        # Find page providing this capability
        target_page: ProductPage | None = None
        target_actions: list[ProductAction] = []

        # 1. Match actions with expected_effects or mutates matching capability
        cap_state_keys = set()
        for p in (cap.produces_state or []):
            k = p.get("key") if isinstance(p, dict) else getattr(p, "key", "")
            if k:
                cap_state_keys.add(k)

        matching_actions = []
        for a in all_actions:
            action_mutates = set(a.mutates or [])
            for eff in (a.expected_effect or []):
                k = eff.get("key") if isinstance(eff, dict) else getattr(eff, "key", "")
                if k:
                    action_mutates.add(k)
            if cap_state_keys and (cap_state_keys & action_mutates):
                matching_actions.append(a)

        if matching_actions:
            # Group by page
            action_by_page: dict[uuid.UUID, list[ProductAction]] = {}
            for a in matching_actions:
                action_by_page.setdefault(a.page_id, []).append(a)
            # Pick page with most matching actions
            best_page_id = max(action_by_page.keys(), key=lambda pid: len(action_by_page[pid]))
            target_page = next((p for p in all_pages if p.id == best_page_id), None)
            target_actions = action_by_page[best_page_id]

        # 2. If no action matched by state keys, match page by source_files or URL
        if not target_page and cap.source_files:
            for p in all_pages:
                if any(sf in (p.source_files or []) for sf in cap.source_files):
                    target_page = p
                    target_actions = [a for a in all_actions if a.page_id == p.id]
                    break

        # 3. Fallback: match by capability name pattern in URL
        if not target_page:
            cap_slug = cap.name.lower().replace("_", "")
            for p in all_pages:
                if cap_slug in p.url_pattern.lower().replace("/", "").replace("-", ""):
                    target_page = p
                    target_actions = [a for a in all_actions if a.page_id == p.id]
                    break

        if not target_page:
            logger.info("Deterministic generator: No page found for capability %s", cap.name)
            return None

        # Build steps
        steps: list[ExecutionStep] = []
        page_ids: list[uuid.UUID] = []

        # Check authentication requirement
        needs_auth = (
            target_page.requires_auth
            or (persona and persona.credentials_required)
            or ("auth" in (cap.requires_capabilities or []))
            or ("authentication" in (cap.requires_capabilities or []))
        )

        # Navigate to target page
        if target_page.id not in page_ids:
            page_ids.append(target_page.id)
        steps.append(step_navigate(target_page.url_pattern))

        # Perform interactive actions
        # Every selector in generated internal representation MUST come from Action.selector
        executed_any_action = False
        for act in target_actions:
            if not act.selector or not act.selector.strip():
                # Anti-pattern check: if selector is missing, do NOT guess!
                logger.warning("Action %s on page %s missing selector", act.name, target_page.url_pattern)
                continue

            steps.append(step_locate(act.selector, description=f"Locate {act.name}"))
            if act.action_type == "input":
                steps.append(step_input(act.selector, "test_input", description=f"Enter input into {act.name}"))
            elif act.action_type in ("click", "submit"):
                steps.append(step_click(act.selector, description=f"Click {act.name}"))
            else:
                steps.append(step_click(act.selector, description=f"Perform {act.action_type} on {act.name}"))

            # Evidence capture after action
            steps.append(
                step_capture_evidence(
                    step_id=f"action_{act.id.hex[:8]}",
                    purpose="step_evidence",
                    description=f"Evidence after {act.name}",
                )
            )
            executed_any_action = True

        # State outcome assertions
        produces_assertions: list[StateAssertion] = []
        for p in (cap.produces_state or []):
            k = p.get("key") if isinstance(p, dict) else getattr(p, "key", "")
            v = p.get("value") if isinstance(p, dict) else getattr(p, "value", True)
            if k:
                produces_assertions.append(StateAssertion(key=k, value=v, predicate="eq"))
                steps.append(step_assert(assertion_type=f"state_{k}", value=v, target=k))

        if not produces_assertions:
            produces_assertions.append(StateAssertion(key=f"cap_{cap.name}", value=True, predicate="eq"))
            steps.append(step_assert(assertion_type="page_loaded", value=target_page.url_pattern, target="url_matches"))

        steps.append(
            step_capture_evidence(
                step_id=f"verify_{cap.id.hex[:8]}",
                purpose="verification",
                description=f"Verification evidence for capability {cap.name}",
            )
        )

        requires_assertions: list[StateAssertion] = []
        for r in (cap.requires_state or []):
            rk = r.get("key") if isinstance(r, dict) else getattr(r, "key", "")
            rv = r.get("value") if isinstance(r, dict) else getattr(r, "value", True)
            if rk:
                requires_assertions.append(StateAssertion(key=rk, value=rv, predicate="eq"))
        if needs_auth:
            requires_assertions.append(StateAssertion(key="authenticated", value=True, predicate="eq"))

        mutates_keys = list(cap_state_keys) or [f"cap_{cap.name}"]

        state_contract = FlowStateContract(
            requires=requires_assertions,
            produces=produces_assertions,
            mutates=mutates_keys,
            persona=persona.name if persona else None,
            requires_credential=needs_auth,
        )

        flow_name = goal.name if goal else f"Execute {cap.name.replace('_', ' ').capitalize()}"
        if persona:
            flow_name = f"{flow_name} as {persona.name}"

        json_repr = to_json_representation(
            name=flow_name,
            steps=steps,
            state_contract=state_contract,
            source="deterministic",
            confidence=1.0,
            page_ids=page_ids,
        )
        gherkin = to_gherkin_representation(flow_name, steps)

        return GeneratedFlow(
            name=flow_name,
            goal_id=goal.id if goal else None,
            persona_id=persona.id if persona else None,
            page_ids=page_ids,
            state_contract=state_contract,
            internal=steps,
            json_repr=json_repr,
            gherkin=gherkin,
            source="deterministic",
            confidence=1.0,
        )

    def _build_auth_substeps(
        self,
        all_pages: list[ProductPage],
        all_actions: list[ProductAction],
    ) -> tuple[list[ExecutionStep], ProductPage | None]:
        """Construct standard authentication steps using discovered login page/actions."""
        # Find login page
        auth_page = next(
            (p for p in all_pages if "/login" in p.url_pattern or "/signin" in p.url_pattern or "auth" in p.url_pattern),
            None,
        )
        if not auth_page and all_pages:
            auth_page = all_pages[0]

        steps: list[ExecutionStep] = []
        if not auth_page:
            return steps, None

        auth_actions = [a for a in all_actions if a.page_id == auth_page.id]
        email_act = next((a for a in auth_actions if "email" in a.selector.lower() or "user" in a.selector.lower()), None)
        pwd_act = next((a for a in auth_actions if "pass" in a.selector.lower()), None)
        submit_act = next((a for a in auth_actions if a.action_type in ("submit", "click") and ("sign" in a.name.lower() or "log" in a.name.lower() or "submit" in a.name.lower())), None)

        steps.append(step_navigate(auth_page.url_pattern, description="Navigate to authentication page"))
        if email_act and email_act.selector:
            steps.append(step_locate(email_act.selector, description="Locate email input"))
            steps.append(step_input(email_act.selector, "{credential.email}", description="Input user email"))
        else:
            steps.append(step_input("input[type=email]", "{credential.email}", description="Input user email"))

        if pwd_act and pwd_act.selector:
            steps.append(step_locate(pwd_act.selector, description="Locate password input"))
            steps.append(step_input(pwd_act.selector, "{credential.password}", description="Input user password"))
        else:
            steps.append(step_input("input[type=password]", "{credential.password}", description="Input user password"))

        if submit_act and submit_act.selector:
            steps.append(step_locate(submit_act.selector, description="Locate sign in button"))
            steps.append(step_click(submit_act.selector, description="Click Sign In"))
        else:
            steps.append(step_click("button[type=submit]", description="Click Sign In"))

        steps.append(step_assert("url_matches", "/dashboard", description="Assert URL reaches authenticated area"))
        steps.append(step_capture_evidence("auth_complete", purpose="verification", description="Evidence of successful login"))

        return steps, auth_page
