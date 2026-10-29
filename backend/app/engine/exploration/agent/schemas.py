"""Validated schemas for exploration-agent proposals.

The model is an untrusted proposer. Everything it returns is parsed into these
models before any deterministic validation or browser action occurs.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class ExplorationAction(str, Enum):
    OPEN_LINK = "open_link"
    CLICK_CONTROL = "click_control"
    OPEN_MENU_OR_TAB = "open_menu_or_tab"
    EXPAND_ACCORDION = "expand_accordion"
    SCROLL_TO_LOAD_MORE = "scroll_to_load_more"
    GO_BACK = "go_back"


CLICK_ACTIONS = {
    ExplorationAction.CLICK_CONTROL,
    ExplorationAction.OPEN_MENU_OR_TAB,
    ExplorationAction.EXPAND_ACCORDION,
}


class AgentActionProposal(BaseModel):
    """One bounded exploration action proposed by the model or the fallback."""

    model_config = ConfigDict(extra="ignore")

    action: ExplorationAction
    target: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=500)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    expected_effect: str | None = Field(default=None, max_length=500)

    _source: str | None = PrivateAttr(default=None)

    @property
    def source(self) -> str | None:
        """Who produced this proposal: ``"ai"`` or ``"bfs_fallback"``."""
        return self._source

    def with_source(self, source: str) -> "AgentActionProposal":
        self._source = source
        return self


class DiscoveredCapability(BaseModel):
    """A capability observed on a page, with the evidence used to rank it."""

    model_config = ConfigDict(extra="ignore")

    name: str
    kind: str = "control"
    url: str
    node_id: str
    source: str = "observed"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)
