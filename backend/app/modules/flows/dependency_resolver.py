"""Deterministically resolve flow and reusable capability dependencies."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


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
            id=str(flow.id), version=int(flow.version), name=flow.name,
            steps=list(flow.steps or []), preconditions=flow.preconditions,
            success_condition=flow.success_condition,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "version": self.version, "name": self.name,
            "steps": self.steps, "preconditions": self.preconditions,
            "success_condition": self.success_condition,
        }


def resolve_dependency_plan(target: Any, flows: list[Any]) -> list[dict]:
    """Return setup flows in dependency order, excluding the target flow."""
    by_id = {str(flow.id): flow for flow in flows}
    if str(target.id) not in by_id:
        by_id[str(target.id)] = target

    providers: dict[str, list[Any]] = {}
    for flow in by_id.values():
        for capability in flow.provides_capabilities or []:
            providers.setdefault(str(capability), []).append(flow)

    ordered: list[Any] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(flow: Any) -> None:
        flow_id = str(flow.id)
        if flow_id in visiting:
            cycle = visiting[visiting.index(flow_id):] + [flow_id]
            raise DependencyResolutionError("DEPENDENCY_CYCLE", "Flow dependency cycle detected", cycle)
        if flow_id in visited:
            return
        visiting.append(flow_id)
        for dependency in flow.dependencies or []:
            kind = dependency.get("kind")
            value = dependency.get("value")
            if kind == "flow":
                try:
                    dependency_id = str(uuid.UUID(str(value)))
                except ValueError as exc:
                    raise DependencyResolutionError("INVALID_DEPENDENCY", f"Invalid dependency flow ID: {value}") from exc
                candidate = by_id.get(dependency_id)
                if candidate is None:
                    raise DependencyResolutionError("MISSING_DEPENDENCY", f"Required flow {dependency_id} was not found")
            elif kind == "capability":
                matches = providers.get(str(value), [])
                if not matches:
                    raise DependencyResolutionError("MISSING_CAPABILITY", f"No flow provides required capability '{value}'")
                if len(matches) > 1:
                    raise DependencyResolutionError("AMBIGUOUS_CAPABILITY", f"Multiple flows provide required capability '{value}'")
                candidate = matches[0]
            else:
                raise DependencyResolutionError("INVALID_DEPENDENCY", "Dependency kind must be 'flow' or 'capability'")
            if str(candidate.id) == flow_id:
                raise DependencyResolutionError("DEPENDENCY_CYCLE", "A flow cannot depend on itself", [flow_id, flow_id])
            visit(candidate)
        visiting.pop()
        visited.add(flow_id)
        if flow_id != str(target.id):
            ordered.append(flow)

    visit(target)
    return [PlannedFlow.from_flow(flow).to_dict() for flow in ordered]
