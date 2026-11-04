"""Exploration agent using epistemic application understanding.

Maintains backward compatibility with legacy ExplorationAgent while using
the active epistemic investigation loop.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.engine.exploration.agent.epistemic_agent import EpistemicExplorationAgent

logger = logging.getLogger(__name__)


class ExplorationAgent(EpistemicExplorationAgent):
    """Exploration agent for investigating web applications."""

    def __init__(
        self,
        engine: Any,
        page: Any,
        event_emitter: Callable[[str, dict], Any] | None = None,
        *,
        provider: Any | None = None,
        budget: dict[str, int] | None = None,
        credentials: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(
            engine,
            page,
            event_emitter,
            provider=provider,
            budget=budget,
            credentials=credentials,
            clock=clock,
        )


__all__ = ["ExplorationAgent", "EpistemicExplorationAgent"]
