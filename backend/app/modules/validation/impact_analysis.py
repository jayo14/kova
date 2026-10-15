"""Change detection and graph-traversal impact analysis engine."""
from __future__ import annotations

import re
from typing import Any

from app.modules.flows.dependency_resolver import (
    ExecutionPlan,
    _extract_contract,
    _keys_collide,
)
from app.modules.validation.graph_traverser import (
    EntitySet,
    _get_field,
    _get_list,
    _is_active_flow,
    capabilities_for_files,
    downstream_flows,
    file_matches_pattern,
    flows_consuming_states,
    flows_producing_states,
    flows_touching_capabilities,
    invariants_for_capabilities,
    minimum_execution_plan,
    state_downstream_flows,
)
from app.modules.validation.schemas import FlowRef, ImpactReport, InvariantRef


def extract_files_from_diff(diff_content: str | None) -> list[str]:
    """Extract list of modified file paths from a unified git diff."""
    if not diff_content:
        return []
    files: set[str] = set()
    for line in diff_content.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.add(path)
        elif line.startswith("--- a/") and not line.startswith("--- a/dev/null"):
            path = line[6:].strip()
            if path:
                files.add(path)
        elif line.startswith("diff --git a/"):
            parts = line.split()
            if len(parts) >= 4:
                p = parts[3].removeprefix("b/").strip()
                if p:
                    files.add(p)
    return sorted(files)


# Alias for backward compatibility
_file_matches_pattern = file_matches_pattern


class ChangeImpactAnalyzer:
    """Deterministically traverses the Product Graph from code changes to minimal execution plan."""

    def __init__(
        self,
        product_model: dict | None = None,
        flows: list[Any] | None = None,
        product_graph: Any | None = None,
    ):
        if product_graph is not None:
            self.graph = product_graph
            if flows and not _get_list(self.graph, "flows"):
                if isinstance(self.graph, dict):
                    self.graph["flows"] = list(flows)
        elif product_model:
            self.graph = dict(product_model)
            if flows and "flows" not in self.graph:
                self.graph["flows"] = list(flows)
        else:
            self.graph = {"flows": list(flows or [])}

        self.product_model = product_model or {}
        self.flows = flows or []

    def analyze(
        self,
        changed_files: list[str] | None = None,
        diff_content: str | None = None,
        commit_message: str | None = None,
        persona: str | None = None,
    ) -> ImpactReport:
        files: set[str] = set(changed_files or [])
        if diff_content:
            files.update(extract_files_from_diff(diff_content))

        cleaned_files = sorted(f.strip() for f in files if f.strip())
        raw_caps = _get_list(self.graph, "capabilities")
        raw_pages = _get_list(self.graph, "pages")
        product_graph_consulted = bool(raw_caps or raw_pages)

        # Empty Product Graph handling: report honestly when files changed
        if not product_graph_consulted and cleaned_files:
            return ImpactReport(
                changed_files=cleaned_files,
                affected_capabilities=[],
                affected_routes=[],
                reasons={},
                confidence=0.0,
                uncertainty=["No Product Graph available; cannot perform targeted validation. Run Product Discovery first."],
                recommended_scope="full",
                downstream_effects=[],
                product_graph_consulted=False,
                unmatched_files=cleaned_files,
                affected_flows=[],
                affected_invariants=[],
                minimal_execution_plan=None,
                graph_traversal_log=[
                    "No Product Graph available; cannot perform graph traversal.",
                ],
            )

        if not cleaned_files and not commit_message:
            return ImpactReport(
                changed_files=[],
                affected_capabilities=[],
                affected_routes=[],
                reasons={},
                confidence=1.0,
                uncertainty=["No file changes or diff provided; defaulting to targeted validation."],
                recommended_scope="targeted",
                downstream_effects=[],
                product_graph_consulted=product_graph_consulted,
                unmatched_files=[],
                affected_flows=[],
                affected_invariants=[],
                minimal_execution_plan=ExecutionPlan(steps=[]) if product_graph_consulted else None,
                graph_traversal_log=["No changes detected."],
            )

        log: list[str] = []
        affected_capabilities: set[str] = set()
        affected_routes: set[str] = set()
        reasons: dict[str, str] = {}
        downstream_effects: list[str] = []
        uncertainties: list[str] = []
        unmatched_files: list[str] = []

        shared_cap_changed = False
        has_shared_caps = any(
            _get_field(cap, "kind") == "shared" or _get_field(cap, "is_shared") is True
            for cap in raw_caps
        )
        if product_graph_consulted and not has_shared_caps:
            uncertainties.append("Product Graph contains no shared capabilities; cannot assess shared component impact.")

        # 1. Map changed files to capabilities and routes
        matched_caps_set = capabilities_for_files(self.graph, cleaned_files)

        for f in cleaned_files:
            file_matched = False
            route_match = re.search(r"(?:app|pages)/([a-zA-Z0-9_\-\/\[\]]+?)(?:/page|\.[a-zA-Z]+$)", f)
            clean_route = None
            if route_match:
                extracted_route = "/" + route_match.group(1).replace("[", ":").replace("]", "")
                clean_route = re.sub(r"/+", "/", extracted_route)

            for cap in raw_caps:
                cap_name = _get_field(cap, "name", "")
                if not cap_name:
                    continue

                source_files = _get_field(cap, "source_files", []) or []
                routes = _get_field(cap, "routes", []) or []
                is_shared = _get_field(cap, "kind") == "shared" or _get_field(cap, "is_shared") is True

                matched_by_source = any(file_matches_pattern(f, pattern) for pattern in source_files)
                matched_by_route = clean_route is not None and clean_route in routes

                if matched_by_source or matched_by_route or (cap in matched_caps_set):
                    file_matched = True
                    affected_capabilities.add(cap_name)

                    if matched_by_source:
                        reasons[cap_name] = f"File {f} is listed as a source file for capability '{cap_name}' in the Product Graph."
                        log.append(f"Changed file {f} matched capability '{cap_name}' (source_files match).")
                    elif matched_by_route:
                        reasons[cap_name] = f"Source route file {f} matches route '{clean_route}' for capability '{cap_name}' in the Product Graph."
                        log.append(f"Changed file {f} matched capability '{cap_name}' (route match '{clean_route}').")
                    else:
                        reasons[cap_name] = f"File {f} traversed to capability '{cap_name}' via page mapping."
                        log.append(f"Changed file {f} traversed to capability '{cap_name}' via page mapping.")

                    if clean_route is not None:
                        affected_routes.add(clean_route)
                        reasons[clean_route] = f"Source route file {f} was directly modified."

                    if is_shared:
                        shared_cap_changed = True
                        downstream_effects.append(
                            f"Shared capability '{cap_name}' modified by {f}; affects downstream workflows."
                        )

            if not file_matched:
                unmatched_files.append(f)
                if clean_route is not None:
                    affected_routes.add(clean_route)
                    reasons[clean_route] = f"Source route file {f} was directly modified."

        # 2. Graph Traversal: Direct flows touching capabilities
        flows_direct: set[Any] = flows_touching_capabilities(self.graph, matched_caps_set)
        if matched_caps_set:
            cap_names_list = sorted([_get_field(c, "name") for c in matched_caps_set])
            direct_names_list = sorted([_get_field(f, "name") for f in flows_direct])
            log.append(f"Capabilities {cap_names_list} touched by flows: {direct_names_list}.")

        # If shared capability changed, any flow depending on that capability is also affected
        if shared_cap_changed:
            all_active_flows = [f for f in _get_list(self.graph, "flows") if _is_active_flow(f)]
            shared_names = {
                _get_field(c, "name")
                for c in matched_caps_set
                if _get_field(c, "kind") == "shared" or _get_field(c, "is_shared") is True
            }
            for flow in all_active_flows:
                flow_deps = _get_field(flow, "dependencies", []) or []
                depends_on_shared = any(
                    isinstance(d, dict)
                    and d.get("kind") == "capability"
                    and d.get("value") in shared_names
                    for d in flow_deps
                )
                if depends_on_shared:
                    flows_direct.add(flow)

        # 3. State Downstream Traversal (produces/mutates -> requires)
        flows_state_downstream = EntitySet()
        for df in list(flows_direct):
            contract = _extract_contract(df)
            df_name = _get_field(df, "name", str(_get_field(df, "id", "")))
            for p in contract.produces:
                log.append(f"Flow '{df_name}' produces state '{p.key}'.")
            for m in contract.mutates:
                log.append(f"Flow '{df_name}' mutates state '{m}'.")

            sd_flows = state_downstream_flows(self.graph, df)
            for sf in sd_flows:
                if sf not in flows_direct:
                    flows_state_downstream.add(sf)

        if flows_state_downstream:
            sd_names = sorted([_get_field(f, "name") for f in flows_state_downstream])
            log.append(f"State downstream traversal added: {sd_names}.")

        # 4. Dependency Downstream Traversal (flow -> flow dependencies)
        flows_dep_downstream = EntitySet()
        for df in list(flows_direct):
            dd_flows = downstream_flows(self.graph, df)
            for dep_f in dd_flows:
                if dep_f not in flows_direct and dep_f not in flows_state_downstream:
                    flows_dep_downstream.add(dep_f)

        if flows_dep_downstream:
            dd_names = sorted([_get_field(f, "name") for f in flows_dep_downstream])
            log.append(f"Dependency downstream traversal added: {dd_names}.")

        # Union affected flows (targets only, prerequisites will be sequenced by DependencyResolver)
        all_affected_flows = flows_direct | flows_state_downstream | flows_dep_downstream
        sorted_affected_flows = sorted(
            all_affected_flows,
            key=lambda x: _get_field(x, "name", str(_get_field(x, "id", ""))),
        )

        affected_flow_refs: list[FlowRef] = []
        for f in sorted_affected_flows:
            fid = str(_get_field(f, "id", ""))
            fname = _get_field(f, "name", fid)
            reason = "Direct capability match"
            if f in flows_state_downstream:
                reason = "Consumes state produced or mutated by affected flow"
            elif f in flows_dep_downstream:
                reason = "Flow dependency on affected flow"
            affected_flow_refs.append(FlowRef(id=fid, name=fname, reason=reason, role="target"))

        # 5. Invariants Traversal
        matched_invariants_set = invariants_for_capabilities(self.graph, matched_caps_set)
        affected_invariant_refs: list[InvariantRef] = []
        for inv in sorted(
            matched_invariants_set,
            key=lambda x: _get_field(x, "name", str(_get_field(x, "id", ""))),
        ):
            inv_id = str(_get_field(inv, "id", ""))
            inv_name = _get_field(inv, "name", inv_id)
            inv_assertion = _get_field(inv, "assertion")
            log.append(f"Invariant '{inv_name}' references state from affected capability.")
            affected_invariant_refs.append(
                InvariantRef(
                    id=inv_id,
                    name=inv_name,
                    assertion=str(inv_assertion),
                    reason="References state from affected capability",
                )
            )

        # 6. Minimal Execution Plan Generation via DependencyResolver
        plan: ExecutionPlan | None = None
        if all_affected_flows:
            plan = minimum_execution_plan(self.graph, all_affected_flows, persona=persona)
            step_names = [s.flow_name or s.flow_id for s in plan.steps]
            log.append(f"Minimum execution plan: {step_names}.")
        else:
            plan = ExecutionPlan(steps=[], estimated_cost=0, unresolved=[], warnings=[])

        # 7. Advisory commit message analysis
        if commit_message:
            msg_lower = commit_message.lower()
            if any(term in msg_lower for term in ["breaking", "migration", "refactor"]):
                uncertainties.append("Commit message signals refactor or breaking change; broader impact possible.")

        # 8. Determine confidence and recommended validation scope
        confidence = 1.0
        recommended_scope = "targeted"

        if shared_cap_changed:
            recommended_scope = "expanded"
            uncertainties.append("Shared system capability modified; recommended scope expanded to verify downstream workflows.")
            confidence = min(confidence, 0.85)

        if unmatched_files:
            if recommended_scope == "targeted":
                recommended_scope = "expanded"
            uncertainties.append(
                f"{len(unmatched_files)} modified file(s) could not be mapped to known capabilities in the Product Graph: "
                f"{', '.join(unmatched_files[:3])}{'...' if len(unmatched_files) > 3 else ''}; expanding scope to avoid missing regressions."
            )
            confidence = min(confidence, 0.60)

        if commit_message and any(term in commit_message.lower() for term in ["breaking", "migration", "refactor"]):
            if recommended_scope == "targeted":
                recommended_scope = "expanded"
            confidence = min(confidence, 0.80)

        if len(sorted_affected_flows) > 5 or len(affected_capabilities) > 3:
            if recommended_scope == "targeted":
                recommended_scope = "expanded"

        if len(cleaned_files) > 20 or len(sorted_affected_flows) > 20:
            recommended_scope = "full"
            uncertainties.append("Large scope of changes; recommended full regression validation.")
            confidence = min(confidence, 0.75)

        if confidence < 0.60:
            recommended_scope = "full"

        return ImpactReport(
            changed_files=cleaned_files,
            affected_capabilities=sorted(affected_capabilities),
            affected_routes=sorted(affected_routes),
            reasons=reasons,
            confidence=confidence,
            uncertainty=uncertainties,
            recommended_scope=recommended_scope,
            downstream_effects=downstream_effects,
            product_graph_consulted=product_graph_consulted,
            unmatched_files=unmatched_files,
            affected_flows=affected_flow_refs,
            affected_invariants=affected_invariant_refs,
            minimal_execution_plan=plan,
            graph_traversal_log=log,
        )
