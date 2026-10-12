"""Risk-aware regression flow selector with explainable selection reasons."""
from __future__ import annotations

import uuid
from typing import Any

from app.modules.validation.schemas import ImpactReport


class RegressionFlowSelector:
    """Selects and orders executable flows based on change impact, dependencies, and criticality."""

    def __init__(self, flows: list[Any]):
        self.flows = flows

    def select(
        self,
        impact_report: ImpactReport,
        scope: str = "targeted",
        previously_failing_flow_ids: set[str] | None = None,
    ) -> tuple[list[Any], dict[str, str], dict[str, str]]:
        """Select flows and return (selected_flows, selection_reasons, exclusion_reasons)."""
        prev_failing = previously_failing_flow_ids or set()
        selected_map: dict[str, Any] = {}
        selection_reasons: dict[str, str] = {}
        exclusion_reasons: dict[str, str] = {}

        # If impact analysis confidence is low, widen targeted scope automatically per principle:
        effective_scope = scope
        if scope == "targeted" and impact_report.confidence < 0.70:
            effective_scope = "expanded"

        # 1. Full regression scope: select all active flows
        if effective_scope == "full":
            for flow in self.flows:
                flow_id = str(getattr(flow, "id", ""))
                status = getattr(flow, "status", "active")
                if status in {"disabled", "stale"}:
                    exclusion_reasons[flow_id] = f"Flow is marked as {status}."
                    continue
                selected_map[flow_id] = flow
                selection_reasons[flow_id] = "Included under full regression scope."
            return self._order_and_resolve_dependencies(selected_map, selection_reasons, exclusion_reasons)

        affected_caps = set(impact_report.affected_capabilities)
        affected_routes = set(impact_report.affected_routes)

        # 2. Targeted & Expanded evaluation
        for flow in self.flows:
            flow_id = str(getattr(flow, "id", ""))
            status = getattr(flow, "status", "active")
            criticality = getattr(flow, "criticality", "medium")
            cap = getattr(flow, "capability", None)
            routes = set(getattr(flow, "routes", []) or [])
            steps = getattr(flow, "steps", []) or []

            if status in {"disabled", "stale"}:
                exclusion_reasons[flow_id] = f"Flow is marked as {status}."
                continue

            # Check if steps navigate to an affected route
            for step in steps:
                action = step.get("action", "") if isinstance(step, dict) else getattr(step, "action", "")
                val = step.get("value") or (step.get("target") or {}).get("url") if isinstance(step, dict) else getattr(step, "value", None)
                if action == "navigate" and val:
                    for aff_r in affected_routes:
                        if aff_r in str(val):
                            routes.add(aff_r)

            # Direct match: capability match
            if cap and cap in affected_caps:
                selected_map[flow_id] = flow
                selection_reasons[flow_id] = f"Flow validates directly affected capability '{cap}'."
                continue

            # Direct match: route match
            matching_routes = routes.intersection(affected_routes)
            if matching_routes:
                selected_map[flow_id] = flow
                selection_reasons[flow_id] = f"Flow exercises modified route(s): {', '.join(sorted(matching_routes))}."
                continue

            # Critical workflows: in expanded scope, always include critical flows
            if effective_scope == "expanded" and criticality == "critical":
                selected_map[flow_id] = flow
                selection_reasons[flow_id] = "Critical core business flow included under expanded regression policy."
                continue

            # Flows that previously failed: always re-test in targeted/expanded validation to verify recovery!
            if flow_id in prev_failing:
                selected_map[flow_id] = flow
                selection_reasons[flow_id] = "Previously failing flow included to verify defect recovery."
                continue

            # If authentication changed, include flows that require authentication
            if "authentication" in affected_caps:
                preconds = getattr(flow, "preconditions", {}) or {}
                if preconds.get("authenticated") or preconds.get("user") or preconds.get("role"):
                    selected_map[flow_id] = flow
                    selection_reasons[flow_id] = "Flow depends on authentication, which was touched by this change."
                    continue

            # If downstream effects detected in expanded scope, include dependent capabilities
            if effective_scope == "expanded" and "course_enrollment" in affected_caps:
                if cap in {"course_access", "assignment_submission"}:
                    selected_map[flow_id] = flow
                    selection_reasons[flow_id] = f"Flow capability '{cap}' is downstream of modified course enrollment."
                    continue

            exclusion_reasons[flow_id] = f"Flow not impacted by change under {effective_scope} scope."

        # If nothing was selected because changes had no match, fallback to minimum safe suite (all critical flows)
        if not selected_map:
            for flow in self.flows:
                flow_id = str(getattr(flow, "id", ""))
                status = getattr(flow, "status", "active")
                criticality = getattr(flow, "criticality", "medium")
                if status == "active" and criticality == "critical":
                    selected_map[flow_id] = flow
                    selection_reasons[flow_id] = "Fallback safe baseline: critical core flow included because impact was unmapped."

        # If still nothing (e.g. no flows marked critical), fallback to first available active flow
        if not selected_map and self.flows:
            first_active = next((f for f in self.flows if getattr(f, "status", "active") == "active"), None)
            if first_active:
                f_id = str(getattr(first_active, "id", ""))
                selected_map[f_id] = first_active
                selection_reasons[f_id] = "Fallback safe baseline: active flow selected."

        return self._order_and_resolve_dependencies(selected_map, selection_reasons, exclusion_reasons)

    def _order_and_resolve_dependencies(
        self,
        selected_map: dict[str, Any],
        selection_reasons: dict[str, str],
        exclusion_reasons: dict[str, str],
    ) -> tuple[list[Any], dict[str, str], dict[str, str]]:
        """Ensure prerequisite flows are included and placed before dependent flows."""
        flows_by_id = {str(getattr(f, "id", "")): f for f in self.flows}
        flows_by_cap: dict[str, Any] = {}
        for f in self.flows:
            for cap in (getattr(f, "provides_capabilities", []) or []):
                flows_by_cap[cap] = f

        # Iteratively pull in dependencies
        added = True
        while added:
            added = False
            for f_id in list(selected_map.keys()):
                flow = selected_map[f_id]
                deps = getattr(flow, "dependencies", []) or []
                for dep in deps:
                    kind = dep.get("kind") if isinstance(dep, dict) else getattr(dep, "kind", None)
                    val = dep.get("value") if isinstance(dep, dict) else getattr(dep, "value", None)
                    prereq_flow = None
                    if kind == "flow" and val in flows_by_id:
                        prereq_flow = flows_by_id[val]
                    elif kind == "capability" and val in flows_by_cap:
                        prereq_flow = flows_by_cap[val]

                    if prereq_flow:
                        p_id = str(getattr(prereq_flow, "id", ""))
                        if p_id not in selected_map:
                            selected_map[p_id] = prereq_flow
                            selection_reasons[p_id] = f"Prerequisite dependency for selected flow '{getattr(flow, 'name', f_id)}'."
                            exclusion_reasons.pop(p_id, None)
                            added = True

        # Topological sorting for dependency order
        ordered: list[Any] = []
        visited: set[str] = set()

        def visit(item_id: str):
            if item_id in visited or item_id not in selected_map:
                return
            visited.add(item_id)
            fl = selected_map[item_id]
            for dep in (getattr(fl, "dependencies", []) or []):
                val = dep.get("value") if isinstance(dep, dict) else getattr(dep, "value", None)
                kind = dep.get("kind") if isinstance(dep, dict) else getattr(dep, "kind", None)
                if kind == "flow" and val in selected_map:
                    visit(str(val))
                elif kind == "capability" and val in flows_by_cap:
                    target_id = str(getattr(flows_by_cap[val], "id", ""))
                    if target_id in selected_map:
                        visit(target_id)
            ordered.append(fl)

        for fid in list(selected_map.keys()):
            visit(fid)

        return ordered, selection_reasons, exclusion_reasons
