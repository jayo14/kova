from __future__ import annotations

import logging
import uuid

from app.modules.flows.schemas import StateAssertion
from app.modules.product_graph.schemas import Action, Capability, Invariant, Page

logger = logging.getLogger(__name__)


class InvariantInferrer:
    def __init__(self, project_id: uuid.UUID):
        self.project_id = project_id

    def infer_invariants(
        self,
        pages: list[Page],
        actions: list[Action],
        capabilities: list[Capability],
    ) -> list[Invariant]:
        """Propose invariants from discovered actions, routes, and capabilities."""
        invariants: list[Invariant] = []
        mutated_keys = {k for a in actions for k in a.mutates}

        if "enrolled" in mutated_keys:
            invariants.append(
                Invariant(
                    project_id=self.project_id,
                    name="Enrolled course appears in student dashboard",
                    assertion=StateAssertion(key="enrolled", value=True, predicate="eq"),
                    source="inferred",
                    confidence=0.5,
                )
            )

        if "authenticated" in mutated_keys:
            invariants.append(
                Invariant(
                    project_id=self.project_id,
                    name="User authentication persists across protected pages",
                    assertion=StateAssertion(key="authenticated", value=True, predicate="eq"),
                    source="inferred",
                    confidence=0.7,
                )
            )

        if "cart" in mutated_keys:
            invariants.append(
                Invariant(
                    project_id=self.project_id,
                    name="Cart item addition persists to checkout",
                    assertion=StateAssertion(key="cart_updated", value=True, predicate="eq"),
                    source="inferred",
                    confidence=0.5,
                )
            )

        if any(k in mutated_keys for k in ("profile_updated", "saved")):
            invariants.append(
                Invariant(
                    project_id=self.project_id,
                    name="Data modifications reflect on subsequent page views",
                    assertion=StateAssertion(key="saved", value=True, predicate="eq"),
                    source="inferred",
                    confidence=0.5,
                )
            )

        return invariants
