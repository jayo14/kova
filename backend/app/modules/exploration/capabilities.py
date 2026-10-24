"""Structured representation of discovered application capabilities.

Distinguishes between pages (locations), UI controls, capabilities (what a user can accomplish),
and complete user workflows, with explicit separation between direct observation and inference.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class CapabilityInput(BaseModel):
    """An input field or parameter observed on a form or workflow."""
    name: str
    type: str = "text"  # text, email, password, file, select, textarea, number
    selector: str | None = None
    label: str | None = None
    required: bool = False
    sample_value: Any = None

    model_config = ConfigDict(from_attributes=True)


class CapabilityVerification(BaseModel):
    """Verifiable outcome criteria associated with a capability."""
    method: Literal["text_visible", "element_visible", "url_matches", "record_persisted", "status_code", "state_mutation"]
    target: str | dict[str, Any]
    expected: Any = None
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DiscoveredCapability(BaseModel):
    """A capability represents functionality the application allows a user to accomplish.
    
    Distinct from a page (a location) or an element (a control).
    """
    id: str = Field(default_factory=lambda: f"cap-{uuid.uuid4().hex[:8]}")
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    user_goal: str = ""  # The outcome the user is trying to achieve
    user_role: str = "visitor"  # The relevant persona/role (visitor, student, admin, etc.)
    entry_point: dict[str, Any] = Field(default_factory=dict)  # route, selector, control
    preconditions: list[str] = Field(default_factory=list)  # auth, existing record, etc.
    actions: list[dict[str, Any]] = Field(default_factory=list)  # sequence of observed interactions
    inputs: list[CapabilityInput] = Field(default_factory=list)  # forms, fields, files
    expected_outcome: str = ""  # Resulting application state or observable effect
    verification_methods: list[CapabilityVerification] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)  # screenshots, observed DOM changes
    discovery_status: Literal["observed", "inferred", "partially_explored", "blocked", "verified"] = "observed"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    provenance: Literal["observed", "inferred", "heuristic"] = "observed"
    coverage_status: Literal["uncovered", "covered"] = "uncovered"
    is_core: bool = False  # True if directly tests application's primary value proposition

    model_config = ConfigDict(from_attributes=True)
