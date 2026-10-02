import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


from typing import Any


class DiscoveredMission(BaseModel):
    id: str = Field(default_factory=lambda: f"mission-{uuid.uuid4().hex[:8]}")
    name: str
    title: str | None = None
    description: str | None = None
    objective: str
    persona: str | None = None
    category: str | None = None  # auth, feature, content, navigation
    journey: list[str] = Field(default_factory=list)
    steps: list[Any] = Field(default_factory=list)
    successCondition: str | dict | None = None
    confidence: float | None = None
    recommended: bool = False
    route_analysis: dict | None = None  # {path, accessible, status, elements_count}
    estimated_time_seconds: int | None = None

    model_config = ConfigDict(from_attributes=True)


class DiscoveryItem(BaseModel):
    label: str
    description: str | None = None


class AgentQuestionOption(BaseModel):
    id: str
    label: str
    description: str | None = None
    icon: str | None = None


class AgentQuestion(BaseModel):
    id: str
    title: str
    description: str | None = None
    type: str = "role"
    options: list[AgentQuestionOption] = Field(default_factory=list)


class CredentialRequest(BaseModel):
    type: str = "login"
    reason: str


class ExplorationCreate(BaseModel):
    url: str = Field(min_length=1, pattern=r"^https?://.+")
    goal: str | None = None


class ExplorationCredentialSubmit(BaseModel):
    email: str
    password: str
    save: bool = False


class ExplorationCreateAccount(BaseModel):
    email: str | None = None
    password: str | None = None


class ExplorationAnswerSubmit(BaseModel):
    question_id: str
    answer: str


class ExplorationRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None = None
    url: str
    goal: str | None = None
    status: str
    selected_role: str | None = None
    discoveries: list[dict] = Field(default_factory=list)
    candidate_missions: list[dict] = Field(default_factory=list)
    question: dict | None = None
    credential_request: dict | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExplorationEventRead(BaseModel):
    id: uuid.UUID
    exploration_id: uuid.UUID
    event_type: str
    payload: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExplorationCancelResponse(BaseModel):
    id: uuid.UUID
    status: str
    message: str
