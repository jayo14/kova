"""Shared exploration resource budget."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CategoryAllocation:
    name: str
    effort_spent: float = 0.0
    actions_taken: int = 0
    evidence_acquired: int = 0
    last_improvement_step: int | None = None
    unproductive_actions: int = 0

    @property
    def productivity(self) -> float:
        if self.effort_spent <= 0:
            return 0.0
        return self.evidence_acquired / self.effort_spent

    @property
    def unproductive_ratio(self) -> float:
        if self.actions_taken <= 0:
            return 0.0
        return self.unproductive_actions / self.actions_taken


@dataclass
class ResourceBudget:
    total_effort: float = 100.0
    effort_spent: float = 0.0
    start_time: float = field(default_factory=time.time)
    max_wall_clock: float = 600.0
    max_pages: int = 50

    categories: dict[str, CategoryAllocation] = field(default_factory=dict)

    actions_taken: int = 0
    steps_taken: int = 0
    evidence_events: int = 0
    unproductive_actions: int = 0
    steps_since_last_evidence: int = 0

    termination_reason: str | None = None
    diminishing_returns_threshold: float = 0.05

    def __post_init__(self) -> None:
        for cat in (
            "auth",
            "discovery",
            "recovery",
            "obstacle",
            "workflow",
            "verification",
        ):
            self.categories.setdefault(cat, CategoryAllocation(name=cat))

    def spend(
        self,
        category: str,
        effort: float = 1.0,
        evidence_gained: bool = False,
        step: int | None = None,
    ) -> bool:
        if self.termination_reason is not None:
            return False

        self.categories.setdefault(category, CategoryAllocation(name=category))
        cat = self.categories[category]

        self.effort_spent += effort
        cat.effort_spent += effort
        self.actions_taken += 1
        cat.actions_taken += 1
        self.steps_taken += 1
        self.steps_since_last_evidence += 1

        if evidence_gained:
            self.evidence_events += 1
            cat.evidence_acquired += 1
            self.unproductive_actions = max(0, self.unproductive_actions - 1)
            cat.unproductive_actions = max(0, cat.unproductive_actions - 1)
            cat.last_improvement_step = step
            self.steps_since_last_evidence = 0
        else:
            self.unproductive_actions += 1
            cat.unproductive_actions += 1

        self._evaluate_termination()
        return self.termination_reason is None

    def _evaluate_termination(self) -> None:
        if self.effort_spent >= self.total_effort:
            self.termination_reason = "budget_exhausted"
            return
        if time.time() - self.start_time >= self.max_wall_clock:
            self.termination_reason = "wall_clock_exhausted"
            return

        if (
            self.actions_taken >= 10
            and self.evidence_events == 0
            and self.steps_since_last_evidence >= 15
        ):
            self.termination_reason = "no_evidence_acquired"
            return

        attempted = [c for c in self.categories.values() if c.actions_taken >= 3]
        if attempted and all(
            c.productivity <= self.diminishing_returns_threshold for c in attempted
        ):
            self.termination_reason = "diminishing_returns"
            return

    def category_productivity(self, category: str) -> float:
        return self.categories.get(category, CategoryAllocation(name=category)).productivity

    def is_category_blocked(self, category: str) -> bool:
        cat = self.categories.get(category)
        if cat is None or cat.actions_taken == 0:
            return False
        return cat.unproductive_ratio >= 0.7 and cat.actions_taken >= 3

    def should_prioritize(self, category: str) -> bool:
        if self.is_category_blocked(category):
            return False
        cat = self.categories.get(category)
        if cat is None:
            return True
        return cat.productivity > self.diminishing_returns_threshold

    @property
    def remaining_effort(self) -> float:
        return max(0.0, self.total_effort - self.effort_spent)

    @property
    def overall_productivity(self) -> float:
        if self.effort_spent <= 0:
            return 0.0
        return self.evidence_events / self.effort_spent

    def summary(self) -> dict[str, Any]:
        return {
            "total_effort": self.total_effort,
            "effort_spent": round(self.effort_spent, 2),
            "remaining_effort": round(self.remaining_effort, 2),
            "actions_taken": self.actions_taken,
            "evidence_events": self.evidence_events,
            "unproductive_actions": self.unproductive_actions,
            "overall_productivity": round(self.overall_productivity, 3),
            "steps_since_last_evidence": self.steps_since_last_evidence,
            "termination_reason": self.termination_reason,
            "categories": {
                name: {
                    "effort_spent": round(c.effort_spent, 2),
                    "actions": c.actions_taken,
                    "evidence": c.evidence_acquired,
                    "productivity": round(c.productivity, 3),
                    "unproductive_ratio": round(c.unproductive_ratio, 3),
                }
                for name, c in self.categories.items()
            },
        }
