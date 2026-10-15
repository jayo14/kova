"""Pure deterministic graph traversal engine for Change Impact Analysis."""
from __future__ import annotations

import collections.abc
import fnmatch
import re
from typing import Any

from app.modules.flows.dependency_resolver import (
    DependencyResolver,
    ExecutionPlan,
    _extract_contract,
    _keys_collide,
)


class EntitySet(collections.abc.MutableSet):
    """Set-like collection that works seamlessly with dicts, ORM models, and Pydantic models."""

    def __init__(self, iterable: Any = None):
        self._items: list[Any] = []
        self._keys: set[Any] = set()
        if iterable:
            for item in iterable:
                self.add(item)

    def _key_for(self, item: Any) -> Any:
        if isinstance(item, (int, str, float, bool)):
            return item
        ident = _get_field(item, "id") or _get_field(item, "name") or _get_field(item, "key")
        if ident:
            return (type(item).__name__, str(ident))
        try:
            return (type(item).__name__, hash(item))
        except TypeError:
            return (type(item).__name__, id(item))

    def __contains__(self, item: Any) -> bool:
        return self._key_for(item) in self._keys

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item: Any) -> None:
        key = self._key_for(item)
        if key not in self._keys:
            self._keys.add(key)
            self._items.append(item)

    def discard(self, item: Any) -> None:
        key = self._key_for(item)
        if key in self._keys:
            self._keys.remove(key)
            self._items = [i for i in self._items if self._key_for(i) != key]

    def __repr__(self) -> str:
        return f"EntitySet({self._items!r})"


def file_matches_pattern(file_path: str, pattern: str) -> bool:
    """Check if file matches exact path, suffix, or glob pattern."""
    p = pattern.strip()
    if not p:
        return False
    # Exact or stripped match
    if file_path == p or file_path.lstrip("/") == p.lstrip("/"):
        return True
    # Suffix match (e.g. pattern "Navbar.tsx" matching "frontend/components/Navbar.tsx")
    if file_path.endswith("/" + p.lstrip("/")):
        return True
    # Glob match
    if fnmatch.fnmatch(file_path, p) or fnmatch.fnmatch(file_path.lstrip("/"), p.lstrip("/")):
        return True
    return False


def _get_list(graph: Any, key: str) -> list[Any]:
    if graph is None:
        return []
    if isinstance(graph, dict):
        return graph.get(key, []) or []
    return getattr(graph, key, []) or []


def _get_field(entity: Any, field_name: str, default: Any = None) -> Any:
    if entity is None:
        return default
    if isinstance(entity, dict):
        return entity.get(field_name, default)
    return getattr(entity, field_name, default)


def _is_active_flow(flow: Any) -> bool:
    if getattr(flow, "active", True) is False:
        return False
    if isinstance(flow, dict) and flow.get("active") is False:
        return False
    status = _get_field(flow, "status", "active")
    if status in ("inactive", "disabled", "archived", "stale"):
        return False
    return True


def _keys_match_or_collide(k1: str, k2: str) -> bool:
    if k1 == k2:
        return True
    if k1.startswith(f"{k2}:") or k2.startswith(f"{k1}:"):
        return True
    if k1.startswith(f"{k2}.") or k2.startswith(f"{k1}."):
        return True
    return _keys_collide(k1, k2)


def capabilities_for_files(graph: Any, changed_files: list[str]) -> EntitySet:
    """Return capabilities whose source_files or routes match any changed file."""
    matched_caps = EntitySet()
    all_caps = _get_list(graph, "capabilities")
    all_pages = _get_list(graph, "pages")

    cleaned_files = [f.strip() for f in (changed_files or []) if f.strip()]
    if not cleaned_files:
        return matched_caps

    for f in cleaned_files:
        route_match = re.search(r"(?:app|pages)/([a-zA-Z0-9_\-\/\[\]]+?)(?:/page|\.[a-zA-Z]+$)", f)
        clean_route = None
        if route_match:
            extracted_route = "/" + route_match.group(1).replace("[", ":").replace("]", "")
            clean_route = re.sub(r"/+", "/", extracted_route)

        pages_matched: set[str] = set()
        for p in all_pages:
            p_source_files = _get_field(p, "source_files", []) or []
            p_url = _get_field(p, "url_pattern", "")
            if any(file_matches_pattern(f, sf) for sf in p_source_files):
                if p_url:
                    pages_matched.add(p_url)
            elif clean_route and (p_url == clean_route or p_url.endswith(clean_route) or clean_route.endswith(p_url)):
                if p_url:
                    pages_matched.add(p_url)

        for cap in all_caps:
            source_files = _get_field(cap, "source_files", []) or []
            routes = _get_field(cap, "routes", []) or []

            matched_by_source = any(file_matches_pattern(f, pattern) for pattern in source_files)
            matched_by_route = clean_route is not None and clean_route in routes
            matched_by_page = any(pu in routes for pu in pages_matched)

            if matched_by_source or matched_by_route or matched_by_page:
                matched_caps.add(cap)

    return matched_caps


def flows_touching_capabilities(graph: Any, caps: collections.abc.Iterable[Any]) -> EntitySet:
    """Return flows whose page_ids include any page that hosts any of the given capabilities,

    or whose capability name, provides_capabilities, or provider_flow_ids match.
    """
    matched_flows = EntitySet()
    if not caps:
        return matched_flows

    cap_names = {_get_field(c, "name") for c in caps if _get_field(c, "name")}
    cap_ids = {str(_get_field(c, "id")) for c in caps if _get_field(c, "id")}

    cap_routes: set[str] = set()
    explicit_provider_ids: set[str] = set()
    for c in caps:
        for r in _get_field(c, "routes", []) or []:
            cap_routes.add(r)
        for pf in _get_field(c, "provider_flow_ids", []) or []:
            explicit_provider_ids.add(str(pf))

    # Pages that correspond to capabilities
    all_pages = _get_list(graph, "pages")
    matching_page_ids: set[str] = set()
    for p in all_pages:
        pid = str(_get_field(p, "id", ""))
        pattern = _get_field(p, "url_pattern", "")
        if pattern and pattern in cap_routes:
            matching_page_ids.add(pid)
        else:
            for c in caps:
                for sf in _get_field(c, "source_files", []) or []:
                    if any(file_matches_pattern(sf, psf) for psf in (_get_field(p, "source_files", []) or [])):
                        if pid:
                            matching_page_ids.add(pid)

    for flow in _get_list(graph, "flows"):
        if not _is_active_flow(flow):
            continue
        fid = str(_get_field(flow, "id", ""))
        fcap = _get_field(flow, "capability", "")
        f_provides = set(_get_field(flow, "provides_capabilities", []) or [])
        f_pages = {str(pid) for pid in (_get_field(flow, "page_ids", []) or [])}
        f_routes = set(_get_field(flow, "routes", []) or [])

        # Check navigation URLs in steps
        for step in (_get_field(flow, "steps", []) or []):
            if isinstance(step, dict):
                act = step.get("action") or step.get("type")
                if act == "navigate":
                    val = step.get("url") or step.get("value")
                    if val and isinstance(val, str):
                        f_routes.add(val)

        if fid in explicit_provider_ids:
            matched_flows.add(flow)
        elif fcap in cap_names or bool(f_provides & cap_names):
            matched_flows.add(flow)
        elif bool(f_pages & matching_page_ids):
            matched_flows.add(flow)
        elif bool(f_routes & cap_routes):
            matched_flows.add(flow)

    return matched_flows


def flows_consuming_states(graph: Any, states: set[str]) -> EntitySet:
    """Return flows whose state_contract.requires references any of the given state keys."""
    matched_flows = EntitySet()
    if not states:
        return matched_flows

    for flow in _get_list(graph, "flows"):
        if not _is_active_flow(flow):
            continue
        contract = _extract_contract(flow)
        req_keys = {r.key for r in contract.requires}
        preconds = _get_field(flow, "preconditions", {}) or {}
        if isinstance(preconds, dict):
            req_keys.update(preconds.keys())

        for s in states:
            if any(_keys_match_or_collide(s, rk) for rk in req_keys):
                matched_flows.add(flow)
                break
    return matched_flows


def flows_producing_states(graph: Any, states: set[str]) -> EntitySet:
    """Return flows whose state_contract.produces references any of the given state keys."""
    matched_flows = EntitySet()
    if not states:
        return matched_flows

    for flow in _get_list(graph, "flows"):
        if not _is_active_flow(flow):
            continue
        contract = _extract_contract(flow)
        prod_keys = {p.key for p in contract.produces} | set(contract.mutates)
        for s in states:
            if any(_keys_match_or_collide(s, pk) for pk in prod_keys):
                matched_flows.add(flow)
                break
    return matched_flows


def downstream_flows(graph: Any, root_flow: Any) -> EntitySet:
    """BFS from root_flow through Dependency edges (flow → flow dependencies)."""
    active_flows = [f for f in _get_list(graph, "flows") if _is_active_flow(f)]
    all_deps = _get_list(graph, "dependencies")

    root_id = str(_get_field(root_flow, "id", ""))
    root_name = _get_field(root_flow, "name", "")
    visited_ids: set[str] = {root_id} if root_id else set()
    downstream = EntitySet()
    queue = [root_flow]

    while queue:
        curr = queue.pop(0)
        curr_id = str(_get_field(curr, "id", ""))
        curr_name = _get_field(curr, "name", "")

        for cand in active_flows:
            cand_id = str(_get_field(cand, "id", ""))
            if cand_id in visited_ids:
                continue

            depends_on_curr = False
            # Check flow's own dependencies
            cand_deps = _get_field(cand, "dependencies", []) or []
            for d in cand_deps:
                if isinstance(d, dict):
                    k = d.get("kind")
                    v = str(d.get("value", ""))
                    if k == "flow" and (v == curr_id or v == curr_name):
                        depends_on_curr = True
                        break

            # Check graph dependencies table
            if not depends_on_curr and all_deps:
                for gd in all_deps:
                    g_fid = str(_get_field(gd, "flow_id", ""))
                    g_kind = _get_field(gd, "depends_on_kind", "")
                    g_target = str(_get_field(gd, "depends_on_id", ""))
                    if g_fid == cand_id and g_kind == "flow" and (g_target == curr_id or g_target == curr_name):
                        depends_on_curr = True
                        break

            if depends_on_curr:
                visited_ids.add(cand_id)
                downstream.add(cand)
                queue.append(cand)

    return downstream


def state_downstream_flows(graph: Any, root_flow: Any) -> EntitySet:
    """BFS from root_flow through state_contract.produces → state_contract.requires edges.

    Catches data flow mutations and state dependencies across flows.
    """
    root_id = str(_get_field(root_flow, "id", ""))
    visited_ids: set[str] = {root_id} if root_id else set()
    downstream = EntitySet()
    queue = [root_flow]

    while queue:
        curr = queue.pop(0)
        contract = _extract_contract(curr)
        produced_keys = {p.key for p in contract.produces} | set(contract.mutates)
        if not produced_keys:
            continue

        consumers = flows_consuming_states(graph, produced_keys)
        for c in consumers:
            cid = str(_get_field(c, "id", ""))
            if cid and cid not in visited_ids:
                visited_ids.add(cid)
                downstream.add(c)
                queue.append(c)

    return downstream


def invariants_for_capabilities(graph: Any, caps: collections.abc.Iterable[Any]) -> EntitySet:
    """Return invariants whose assertion references any state produced by the given capabilities."""
    matched_invs = EntitySet()
    if not caps:
        return matched_invs

    produced_keys: set[str] = set()
    for c in caps:
        c_prod = _get_field(c, "produces_state", []) or []
        for sm in c_prod:
            if isinstance(sm, dict):
                k = sm.get("key")
            elif hasattr(sm, "key"):
                k = getattr(sm, "key")
            else:
                k = str(sm)
            if k:
                produced_keys.add(k)
        cname = _get_field(c, "name")
        if cname:
            produced_keys.add(cname)

    cap_flows = flows_touching_capabilities(graph, caps)
    cap_flow_ids = {str(_get_field(f, "id")) for f in cap_flows}

    all_invariants = _get_list(graph, "invariants")

    for inv in all_invariants:
        assertion = _get_field(inv, "assertion")
        inv_key = None
        if isinstance(assertion, dict):
            inv_key = assertion.get("key")
        elif hasattr(assertion, "key"):
            inv_key = getattr(assertion, "key")

        matches_state = False
        if inv_key:
            if inv_key in produced_keys or any(_keys_match_or_collide(inv_key, pk) for pk in produced_keys):
                matches_state = True

        checked_ids = {str(fid) for fid in (_get_field(inv, "checked_by_flow_ids", []) or [])}
        if matches_state or bool(checked_ids & cap_flow_ids):
            matched_invs.add(inv)

    return matched_invs


def minimum_execution_plan(
    graph: Any, flows: collections.abc.Iterable[Any], persona: str | None = None
) -> ExecutionPlan:
    """Use DependencyResolver to plan minimal valid execution of the given flows.

    De-duplicates prerequisites (e.g. auth runs once).
    """
    target_flows = [f for f in flows if _is_active_flow(f)]
    if not target_flows:
        return ExecutionPlan(steps=[], estimated_cost=0, unresolved=[], warnings=[])

    all_active_flows = [f for f in _get_list(graph, "flows") if _is_active_flow(f)]
    for tf in target_flows:
        if str(_get_field(tf, "id")) not in {str(_get_field(f, "id")) for f in all_active_flows}:
            all_active_flows.append(tf)

    return DependencyResolver.resolve_execution_plan(
        target=target_flows,
        flows=all_active_flows,
        persona=persona,
    )
