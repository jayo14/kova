import uuid
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.flows.schemas import FlowStateContract
from app.modules.product_graph.schemas import AIProposal


class ExecutionStep(BaseModel):
    """An atomic executable step within an internal flow representation."""
    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    action: str = Field(description="Action verb e.g. navigate, locate, click, input, submit, assert, capture_evidence, wait")
    target: str | None = None
    value: Any = None
    description: str | None = None
    purpose: str | None = None
    expected_outcome: str | None = None

    model_config = ConfigDict(extra="ignore")

    def to_runner_dict(self) -> dict[str, Any]:
        """Convert this step into runner-compatible dictionary representation."""
        if self.action == "navigate":
            return {
                "step_id": self.step_id,
                "type": "navigate",
                "value": self.value or self.target,
                "target": {},
                "description": self.description,
            }
        elif self.action in ("click", "submit"):
            target_dict: dict[str, Any] = {}
            if self.target:
                if self.target.startswith("#") or self.target.startswith(".") or self.target.startswith("["):
                    target_dict["css"] = self.target
                else:
                    target_dict["text"] = self.target
            return {
                "step_id": self.step_id,
                "type": self.action,
                "target": target_dict,
                "selector": self.target,
                "description": self.description,
                "expected_outcome": self.expected_outcome,
            }
        elif self.action == "input":
            target_dict = {}
            if self.target:
                if self.target.startswith("#") or self.target.startswith(".") or self.target.startswith("["):
                    target_dict["css"] = self.target
                else:
                    target_dict["text"] = self.target
            return {
                "step_id": self.step_id,
                "type": "type",
                "target": target_dict,
                "selector": self.target,
                "value": str(self.value) if self.value is not None else "",
                "description": self.description,
            }
        elif self.action == "assert":
            return {
                "step_id": self.step_id,
                "type": "assert",
                "target": self.target,
                "value": self.value,
                "description": self.description,
            }
        elif self.action == "capture_evidence":
            return {
                "step_id": self.step_id,
                "type": "capture_evidence",
                "purpose": self.purpose or "verification",
                "description": self.description,
            }
        elif self.action == "locate":
            return {
                "step_id": self.step_id,
                "type": "locate",
                "target": {"css": self.target} if self.target else {},
                "selector": self.target,
                "description": self.description,
            }
        return {
            "step_id": self.step_id,
            "type": self.action,
            "target": self.target,
            "value": self.value,
            "description": self.description,
        }


class GeneratedFlow(BaseModel):
    """A generated flow possessing internal, JSON, and Gherkin representations."""
    name: str = Field(min_length=1, max_length=255)
    goal_id: uuid.UUID | None = None
    persona_id: uuid.UUID | None = None
    page_ids: list[uuid.UUID] = Field(default_factory=list)
    state_contract: FlowStateContract
    internal: list[ExecutionStep] = Field(default_factory=list)
    json_repr: dict[str, Any] = Field(default_factory=dict)
    gherkin: str = ""
    source: Literal["deterministic", "ai_proposal", "user_provided"] = "deterministic"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    model_config = ConfigDict(extra="ignore")


class GenerationRequest(BaseModel):
    """Request payload for generating executable flows from a product graph."""
    project_id: uuid.UUID
    goal_id: uuid.UUID | None = None
    persona_id: uuid.UUID | None = None
    target_capability: str | None = None
    depth: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_targets(self):
        if not self.goal_id and not self.target_capability:
            raise ValueError("At least one of goal_id or target_capability must be provided")
        return self


class GenerationResult(BaseModel):
    """Aggregate result from deterministic and AI flow generation."""
    flows: list[GeneratedFlow] = Field(default_factory=list)
    unresolved_goals: list[str] = Field(default_factory=list)
    ai_proposals: list[AIProposal] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")
