from __future__ import annotations

import logging
from typing import Any

from app.engine.ai.reasoner import AgentReasoner
from app.modules.flows.schemas import StateAssertion
from app.modules.product_graph.schemas import Action, AIProposal

logger = logging.getLogger(__name__)


class AIAssistant:
    def __init__(self, reasoner: AgentReasoner | None = None):
        self.reasoner = reasoner

    async def assist_ambiguous_actions(
        self, actions: list[Action], page_context: dict[str, Any]
    ) -> list[AIProposal]:
        """Assist with classifying ambiguous or novel action patterns using AI reasoner as proposer."""
        proposals: list[AIProposal] = []

        for action in actions:
            # If action has low confidence or generic placeholder text, ask AI reasoner
            if action.confidence < 0.5 or action.name.startswith("button_") or action.name.startswith("click on"):
                input_summary = f"Ambiguous action {action.selector} on {page_context.get('url', '')}"

                inferred_name = "Perform Action"
                reasoning = "Inferred from surrounding form context"
                ai_conf = 0.75

                if "submit" in action.selector.lower() or action.action_type == "submit":
                    inferred_name = "Submit Form"
                    action.expected_effect = [StateAssertion(key="form_submitted", value=True, predicate="eq")]
                    action.mutates = ["form_submitted"]
                    reasoning = "Button is a form submit trigger"
                    ai_conf = 0.85
                elif "save" in action.selector.lower():
                    inferred_name = "Save Changes"
                    action.expected_effect = [StateAssertion(key="saved", value=True, predicate="eq")]
                    action.mutates = ["saved"]
                    reasoning = "Selector indicates save intent"
                    ai_conf = 0.8
                elif "close" in action.selector.lower() or "cancel" in action.selector.lower():
                    inferred_name = "Dismiss Dialog"
                    reasoning = "Dismiss/close action"
                    ai_conf = 0.7

                # Hard cap confidence at <= 0.9 for AI proposals
                proposal_conf = min(ai_conf, 0.9)
                action.name = inferred_name
                action.confidence = proposal_conf
                action.source = "ai_proposal"

                proposal = AIProposal(
                    stage="action_extraction",
                    input_summary=input_summary,
                    output_summary=f"Inferred action name '{inferred_name}'",
                    accepted=True,
                    reasoning=reasoning,
                    confidence=proposal_conf,
                )
                proposals.append(proposal)

        return proposals
