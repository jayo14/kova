"""Explainable change-aware ordering of suite flows (no ML)."""

from __future__ import annotations

import re
from typing import Any

_STOP_WORDS = {
    "app", "src", "lib", "libs", "test", "tests", "spec", "specs", "e2e",
    "page", "pages", "component", "components", "view", "views", "route",
    "routes", "api", "index", "main", "utils", "util", "helper", "helpers",
    "layout", "styles", "style", "types", "type", "data", "server", "client",
    "public", "static", "assets", "features", "feature", "module", "modules",
    "tsx", "jsx", "ts", "js", "py", "css", "scss", "json", "yaml", "yml",
    "md", "html", "sql", "test", "unit", "integration", "fixture", "fixtures",
}

_CRITICALITY_WEIGHT = {
    "critical": 4,
    "high": 3,
    "medium": 1,
    "low": 0,
}


def changed_file_terms(changed_files: list[str]) -> set[str]:
    terms: set[str] = set()
    for path in changed_files or []:
        if not isinstance(path, str):
            continue
        cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", path).lower()
        for token in cleaned.split():
            if len(token) >= 4 and token not in _STOP_WORDS:
                terms.add(token)
    return terms


def _flow_terms(flow: dict[str, Any]) -> dict[str, set[str]]:
    def words(value: Any) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, (list, tuple)):
            value = " ".join(str(item) for item in value)
        elif isinstance(value, dict):
            value = " ".join(str(item) for item in value.values())
        cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", str(value)).lower()
        return {token for token in cleaned.split() if len(token) >= 4 and token not in _STOP_WORDS}

    routes: set[str] = set()
    for route in flow.get("routes") or []:
        routes |= words(route)
    dependencies = flow.get("dependencies") or []
    dependency_terms: set[str] = set()
    for dependency in dependencies:
        if isinstance(dependency, dict):
            dependency_terms |= words(dependency.get("flow_name") or dependency.get("name"))
            dependency_terms |= words(dependency.get("capability"))
        else:
            dependency_terms |= words(dependency)
    return {
        "routes": routes,
        "name": words(flow.get("name")),
        "objective": words(flow.get("objective") or flow.get("description")),
        "capability": words(flow.get("capability")),
        "dependencies": dependency_terms,
        "provides": words(flow.get("provides_capabilities")),
    }


def score_flow(
    flow: dict[str, Any],
    *,
    changed_terms: set[str],
    history: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, list[str]]:
    terms = _flow_terms(flow)
    score = 0
    reasons: list[str] = []
    change_match = False

    route_hits = terms["routes"] & changed_terms
    if route_hits:
        score += 2 * len(route_hits)
        change_match = True
        reasons.append(f"route match: {', '.join(sorted(route_hits))}")
    capability_hits = (terms["capability"] | terms["provides"]) & changed_terms
    if capability_hits:
        score += 2 * len(capability_hits)
        change_match = True
        reasons.append(f"capability match: {', '.join(sorted(capability_hits))}")
    name_hits = terms["name"] & changed_terms
    if name_hits:
        score += len(name_hits)
        change_match = True
        reasons.append(f"name match: {', '.join(sorted(name_hits))}")
    objective_hits = terms["objective"] & changed_terms
    if objective_hits:
        score += len(objective_hits)
        change_match = True
        reasons.append(f"objective match: {', '.join(sorted(objective_hits))}")
    dependency_hits = terms["dependencies"] & changed_terms
    if dependency_hits:
        score += len(dependency_hits)
        change_match = True
        reasons.append(f"dependency match: {', '.join(sorted(dependency_hits))}")

    criticality = str(flow.get("criticality") or "medium").lower()
    weight = _CRITICALITY_WEIGHT.get(criticality, 1)
    if weight:
        score += weight
        if criticality in ("critical", "high"):
            reasons.append(f"criticality: {criticality}")

    flow_id = str(flow.get("id")) if flow.get("id") else None
    flow_history = (history or {}).get(flow_id or "", {})
    if flow_history.get("recent_failure"):
        score += 2
        reasons.append("recent failure")
    if flow_history.get("flaky"):
        score += 3
        reasons.append("flaky history")

    return score, reasons, change_match


def _strip_internal(item: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in item.items()
        if k not in ("_order", "priority_matched")
    }


def prioritize_flows(
    flows: list[dict[str, Any]],
    *,
    mode: str,
    changed_files: list[str],
    history: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return snapshot copies annotated with priority; full/targeted/prioritized semantics."""
    changed_terms = changed_file_terms(changed_files)
    scored: list[dict[str, Any]] = []
    for index, flow in enumerate(flows):
        score, reasons, change_match = score_flow(
            flow, changed_terms=changed_terms, history=history
        )
        item = dict(flow)
        item["priority_score"] = score
        item["priority_reasons"] = reasons
        item["priority_matched"] = change_match
        item["_order"] = index
        scored.append(item)

    if mode == "full":
        return [_strip_internal(item) for item in scored]

    matched = [item for item in scored if item["priority_matched"]]
    ranked = sorted(matched if mode == "targeted" else scored, key=lambda item: (-item["priority_score"], item["_order"]))
    return [_strip_internal(item) for item in ranked]
