"""Deterministically resolve flow execution plans with State, Capability, and Prerequisite semantics."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.modules.flows.schemas import (
    FlowStateContract,
    ResetStrategy,
    StateAssertion,
)


class DependencyResolutionError(ValueError):
    def __init__(self, code: str, message: str, path: list[str] | None = None):
        self.code = code
        self.path = path or []
        super().__init__(message)


@dataclass(frozen=True)
class PlannedFlow:
    id: str
    version: int
    name: str
    steps: list[dict]
    preconditions: dict | None
    success_condition: dict | None

    @classmethod
    def from_flow(cls, flow: Any) -> "PlannedFlow":
        return cls(
            id=str(flow.id),
            version=int(getattr(flow, "version", 1)),
            name=getattr(flow, "name", ""),
            steps=list(getattr(flow, "steps", []) or []),
            preconditions=getattr(flow, "preconditions", None),
            success_condition=getattr(flow, "success_condition", None),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "steps": self.steps,
            "preconditions": self.preconditions,
            "success_condition": self.success_condition,
        }


@dataclass
class ExecutionStep:
    flow_id: str
    role: Literal["prerequisite", "target", "teardown"]
    establishes: list[StateAssertion]
    reason: str
    cost: int
    skip_if_exists: bool = False
    flow_name: str = ""


@dataclass
class ExecutionPlan:
    steps: list[ExecutionStep] = field(default_factory=list)
    estimated_cost: int = 0
    unresolved: list[StateAssertion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _extract_contract(flow: Any) -> FlowStateContract:
    """Extract or construct a FlowStateContract from a flow object."""
    raw_contract = getattr(flow, "state_contract", None)
    if isinstance(raw_contract, FlowStateContract):
        contract = raw_contract.model_copy(deep=True)
    elif isinstance(raw_contract, dict) and raw_contract:
        contract = FlowStateContract.model_validate(raw_contract)
    else:
        contract = FlowStateContract()

    # Legacy provides_capabilities
    existing_prod_keys = {p.key for p in contract.produces}
    for cap in getattr(flow, "provides_capabilities", []) or []:
        cap_str = str(cap)
        if cap_str not in existing_prod_keys:
            contract.produces.append(StateAssertion(key=cap_str, value=True))
            existing_prod_keys.add(cap_str)

    # Always produce self flow presence
    flow_id_str = str(getattr(flow, "id", ""))
    flow_key = f"flow:{flow_id_str}"
    if flow_key not in existing_prod_keys and flow_id_str:
        contract.produces.append(StateAssertion(key=flow_key, value=True))

    # Legacy dependencies
    existing_req_keys = {r.key for r in contract.requires}
    for dep in getattr(flow, "dependencies", []) or []:
        kind = dep.get("kind")
        val = dep.get("value")
        if kind == "flow":
            k = f"flow:{val}"
            if k not in existing_req_keys:
                contract.requires.append(StateAssertion(key=k, value=True))
                existing_req_keys.add(k)
        elif kind == "capability":
            k = str(val)
            if k not in existing_req_keys:
                contract.requires.append(StateAssertion(key=k, value=True))
                existing_req_keys.add(k)

    # Cost
    if hasattr(flow, "cost") and isinstance(getattr(flow, "cost"), int):
        contract.cost = getattr(flow, "cost")

    # Persona
    if not contract.persona and hasattr(flow, "persona") and getattr(flow, "persona"):
        p = getattr(flow, "persona")
        if isinstance(p, str):
            contract.persona = p
        elif isinstance(p, dict):
            contract.persona = p.get("role") or p.get("name")

    # Reset strategy
    if contract.reset_strategy == "none" and hasattr(flow, "reset_strategy") and getattr(flow, "reset_strategy"):
        rs = str(getattr(flow, "reset_strategy"))
        if rs in {"none", "re_establish", "create_new", "skip_if_exists"}:
            contract.reset_strategy = rs  # type: ignore[assignment]
        else:
            # Custom named reset strategy (e.g. "create_new_assignment")
            contract.reset_strategy = "create_new"

    return contract


def _keys_collide(mutated_key: str, required_key: str) -> bool:
    """Check if a mutated/consumed state key touches a required state key."""
    if mutated_key == required_key:
        return True
    m_root = mutated_key.split(".")[0].split("_")[0]
    r_root = required_key.split(".")[0].split("_")[0]
    if m_root and r_root and m_root == r_root:
        return True
    return False


def resolve_execution_plan(
    target: Any | list[Any],
    flows: list[Any],
    current_state: dict[str, Any] | None = None,
    persona: str | None = None,
    available_credentials: set[str] | None = None,
) -> ExecutionPlan:
    """Deterministically plan the minimal valid execution path to reach the required state."""
    targets: list[Any] = target if isinstance(target, list) else [target]
    by_id: dict[str, Any] = {str(f.id): f for f in flows if hasattr(f, "id")}
    by_name: dict[str, Any] = {str(f.name): f for f in flows if hasattr(f, "name") and f.name}
    for t in targets:
        if hasattr(t, "id") and str(t.id) not in by_id:
            by_id[str(t.id)] = t
        if hasattr(t, "name") and t.name and str(t.name) not in by_name:
            by_name[str(t.name)] = t

    all_flows: list[Any] = list(by_id.values())
    contracts: dict[str, FlowStateContract] = {str(f.id): _extract_contract(f) for f in all_flows}

    steps: list[ExecutionStep] = []
    unresolved: list[StateAssertion] = []
    warnings: list[str] = []

    working_state: dict[str, Any] = dict(current_state or {})
    visiting_flows: list[str] = []
    visited_flows: set[str] = set()
    visiting_states: list[str] = []

    def find_providers(req: StateAssertion) -> list[Any]:
        matches: list[Any] = []
        for cand in all_flows:
            c_contract = contracts[str(cand.id)]
            for prod in c_contract.produces:
                if req.is_satisfied_by_assertion(prod):
                    matches.append(cand)
                    break
        return matches

    def rank_candidates(candidates: list[Any]) -> list[Any]:
        def sort_key(cand: Any) -> tuple[int, int, int, str]:
            c_contract = contracts[str(cand.id)]
            cost = c_contract.cost
            persona_penalty = 0
            if persona and c_contract.persona and c_contract.persona != persona:
                persona_penalty = 1
            cred_penalty = 0
            if c_contract.requires_credential:
                if available_credentials is not None:
                    # If persona or flow name not in credentials
                    has_cred = (c_contract.persona in available_credentials) or (getattr(cand, "name", "") in available_credentials)
                    cred_penalty = 0 if has_cred else 1
            return (cost, persona_penalty, cred_penalty, getattr(cand, "name", str(cand.id)))

        return sorted(candidates, key=sort_key)

    def resolve_state(req: StateAssertion, needed_by_name: str) -> bool:
        # Check if already satisfied by working state
        if req.is_satisfied_by_state(working_state):
            return True

        if req.key in visiting_states:
            cycle = visiting_states[visiting_states.index(req.key):] + [req.key]
            unresolved.append(req)
            warnings.append(f"State dependency cycle detected: {' -> '.join(cycle)}")
            return False

        candidates = find_providers(req)
        if not candidates:
            unresolved.append(req)
            warnings.append(f"No flow provides required state '{req.key}' (predicate: {req.predicate}, expected: {req.value})")
            return False

        ranked = rank_candidates(candidates)
        chosen = ranked[0]
        if len(ranked) > 1:
            alt_names = [getattr(c, "name", str(c.id)) for c in ranked[1:]]
            warnings.append(f"Alternative capability providers available: {', '.join(alt_names)}")

        cid = str(chosen.id)
        if cid in visiting_flows:
            cycle = visiting_flows[visiting_flows.index(cid):] + [cid]
            unresolved.append(req)
            warnings.append(f"Flow dependency cycle detected: {' -> '.join(cycle)}")
            return False

        if cid in visited_flows:
            return True

        c_contract = contracts[cid]
        visiting_states.append(req.key)
        visiting_flows.append(cid)

        all_ok = True
        for sub_req in c_contract.requires:
            if not resolve_state(sub_req, getattr(chosen, "name", cid)):
                all_ok = False

        visiting_flows.pop()
        visiting_states.pop()

        if not all_ok:
            return False

        steps.append(
            ExecutionStep(
                flow_id=cid,
                role="prerequisite",
                establishes=list(c_contract.produces),
                reason=f"required by flow '{needed_by_name}' for state '{req.key}'",
                cost=c_contract.cost,
                flow_name=getattr(chosen, "name", ""),
            )
        )
        visited_flows.add(cid)
        for p in c_contract.produces:
            working_state[p.key] = p.value
        return True

    # Plan for each target
    for target_flow in targets:
        tid = str(target_flow.id)
        t_contract = contracts[tid]
        t_name = getattr(target_flow, "name", tid)

        all_ok = True
        for req in t_contract.requires:
            if not resolve_state(req, t_name):
                all_ok = False

        if all_ok and tid not in visited_flows:
            steps.append(
                ExecutionStep(
                    flow_id=tid,
                    role="target",
                    establishes=list(t_contract.produces),
                    reason=f"target flow '{t_name}'",
                    cost=t_contract.cost,
                    flow_name=t_name,
                )
            )
            visited_flows.add(tid)
            for p in t_contract.produces:
                working_state[p.key] = p.value

    # If any required state is unresolved, return empty steps with fail-closed semantics
    if unresolved:
        return ExecutionPlan(
            steps=[],
            estimated_cost=0,
            unresolved=unresolved,
            warnings=warnings,
        )

    # State Contamination check and reset strategy insertion
    idx = 0
    while idx < len(steps):
        s_i = steps[idx]
        flow_i = by_id.get(s_i.flow_id)
        contract_i = contracts.get(s_i.flow_id)
        if not flow_i or not contract_i:
            idx += 1
            continue

        mutates_or_consumes = set(contract_i.mutates) | set(contract_i.consumes)
        if not mutates_or_consumes:
            idx += 1
            continue

        j = idx + 1
        inserted_offset = 0
        while j < len(steps):
            s_j = steps[j]
            flow_j = by_id.get(s_j.flow_id)
            contract_j = contracts.get(s_j.flow_id)
            if not flow_j or not contract_j:
                j += 1
                continue

            for req in contract_j.requires:
                collision = any(_keys_collide(m, req.key) for m in mutates_or_consumes)
                if collision:
                    warnings.append(
                        f"State contamination detected: flow '{s_i.flow_name or s_i.flow_id}' "
                        f"mutates/consumes state '{req.key}' required by later flow '{s_j.flow_name or s_j.flow_id}'"
                    )

                    # Determine reset strategy
                    strategy_name = getattr(flow_i, "reset_strategy", None) or contract_i.reset_strategy
                    if strategy_name == "skip_if_exists":
                        s_j.skip_if_exists = True
                    elif strategy_name == "re_establish":
                        # Check if already re-established between idx and j
                        provs = find_providers(req)
                        if provs:
                            prov = provs[0]
                            existing = next((steps[k] for k in range(idx + 1, j) if steps[k].flow_id == str(prov.id)), None)
                            if not existing:
                                p_contract = contracts[str(prov.id)]
                                re_step = ExecutionStep(
                                    flow_id=str(prov.id),
                                    role="prerequisite",
                                    establishes=list(p_contract.produces),
                                    reason=f"re-establish state '{req.key}' contaminated by '{s_i.flow_name}'",
                                    cost=p_contract.cost,
                                    flow_name=getattr(prov, "name", ""),
                                )
                                steps.insert(j, re_step)
                                j += 1
                                inserted_offset += 1
                    elif strategy_name and strategy_name != "none":
                        # Look up named reset flow in flows (e.g. "create_new_assignment")
                        reset_flow = by_name.get(str(strategy_name)) or by_id.get(str(strategy_name))
                        if reset_flow:
                            existing = next((steps[k] for k in range(idx + 1, j) if steps[k].flow_id == str(reset_flow.id)), None)
                            if existing is not None:
                                existing.role = "teardown"
                                existing.reason = f"reset state for flow '{s_i.flow_name}' before '{s_j.flow_name}'"
                            else:
                                r_contract = contracts[str(reset_flow.id)]
                                teardown_step = ExecutionStep(
                                    flow_id=str(reset_flow.id),
                                    role="teardown",
                                    establishes=list(r_contract.produces),
                                    reason=f"reset state for flow '{s_i.flow_name}' before '{s_j.flow_name}'",
                                    cost=r_contract.cost,
                                    flow_name=getattr(reset_flow, "name", ""),
                                )
                                steps.insert(j, teardown_step)
                                j += 1
                                inserted_offset += 1
            j += 1
        idx += 1 + inserted_offset

    estimated_cost = sum(s.cost for s in steps)
    return ExecutionPlan(
        steps=steps,
        estimated_cost=estimated_cost,
        unresolved=unresolved,
        warnings=warnings,
    )


def resolve_dependency_plan(target: Any, flows: list[Any]) -> list[dict]:
    """Preserve legacy shim returning setup flows in dependency order, excluding the target flow."""
    by_id = {str(flow.id): flow for flow in flows}
    if str(target.id) not in by_id:
        by_id[str(target.id)] = target

    # Legacy validation for ambiguous capability and missing capability
    providers: dict[str, list[Any]] = {}
    for flow in by_id.values():
        for capability in getattr(flow, "provides_capabilities", []) or []:
            providers.setdefault(str(capability), []).append(flow)

    for dependency in getattr(target, "dependencies", []) or []:
        kind = dependency.get("kind")
        value = dependency.get("value")
        if kind == "capability":
            matches = providers.get(str(value), [])
            if not matches:
                raise DependencyResolutionError("MISSING_CAPABILITY", f"No flow provides required capability '{value}'")
            if len(matches) > 1:
                raise DependencyResolutionError("AMBIGUOUS_CAPABILITY", f"Multiple flows provide required capability '{value}'")
        elif kind == "flow":
            try:
                dependency_id = str(uuid.UUID(str(value)))
            except ValueError as exc:
                raise DependencyResolutionError("INVALID_DEPENDENCY", f"Invalid dependency flow ID: {value}") from exc
            if dependency_id not in by_id:
                raise DependencyResolutionError("MISSING_DEPENDENCY", f"Required flow {dependency_id} was not found")
        else:
            raise DependencyResolutionError("INVALID_DEPENDENCY", "Dependency kind must be 'flow' or 'capability'")

    plan = resolve_execution_plan(target, flows)

    if plan.unresolved:
        # Check warnings for cycle
        for w in plan.warnings:
            if "cycle" in w.lower():
                raise DependencyResolutionError("DEPENDENCY_CYCLE", w)
        first_unresolved = plan.unresolved[0]
        if first_unresolved.key.startswith("flow:"):
            raise DependencyResolutionError("MISSING_DEPENDENCY", f"Missing flow dependency: {first_unresolved.key}")
        raise DependencyResolutionError("MISSING_CAPABILITY", f"No flow provides required capability '{first_unresolved.key}'")

    for w in plan.warnings:
        if "cycle" in w.lower():
            raise DependencyResolutionError("DEPENDENCY_CYCLE", w)

    return [
        PlannedFlow.from_flow(by_id[step.flow_id]).to_dict()
        for step in plan.steps
        if step.role == "prerequisite" and step.flow_id in by_id
    ]


class DependencyResolver:
    """Namespace wrapper for deterministic dependency and execution plan resolution."""

    @staticmethod
    def resolve_execution_plan(
        target: Any | list[Any],
        flows: list[Any],
        current_state: dict[str, Any] | None = None,
        persona: str | None = None,
        available_credentials: set[str] | None = None,
    ) -> ExecutionPlan:
        return resolve_execution_plan(
            target=target,
            flows=flows,
            current_state=current_state,
            persona=persona,
            available_credentials=available_credentials,
        )

    @staticmethod
    def resolve_dependency_plan(target: Any, flows: list[Any]) -> list[dict]:
        return resolve_dependency_plan(target=target, flows=flows)

