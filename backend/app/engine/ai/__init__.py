"""Kova AI capability layer.

Architecture invariant: the AI is an untrusted proposer. Every output is parsed
into explicit schemas (`app.engine.ai.schemas`) and further validated by the
deterministic runtime before any browser action executes. The AI can never
mark an execution COMPLETED, never invents credentials, and never navigates
without the runtime's URL security policy.
"""

from app.engine.ai.provider import AIProvider, AIProviderError, get_ai_provider
from app.engine.ai.settings import ai_settings

__all__ = [
    "AIProvider",
    "AIProviderError",
    "get_ai_provider",
    "ai_settings",
]
