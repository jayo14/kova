"""AI settings for Kova's agent capability layer.

Provider-independent: the provider, model, and key all come from environment
variables. When no provider is configured, the agent layer degrades to
deterministic-only behavior (never an error at import time).
"""

from pydantic_settings import BaseSettings


class AISettings(BaseSettings):
    model_config = {
        "env_file": (".env", "backend/.env", "../backend/.env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # "openai_compatible" (default provider kind) | "none"
    AI_PROVIDER: str = "none"
    AI_MODEL: str = ""
    AI_API_KEY: str = ""
    AI_BASE_URL: str = ""          # e.g. https://api.openai.com/v1 or a local gateway
    AI_TEMPERATURE: float = 0.2
    AI_TIMEOUT_SECONDS: float = 60.0
    AI_MAX_OUTPUT_TOKENS: int = 2000

    # Temporary email integration
    TEMPMAIL_PROVIDER: str = "internal"   # reserved for future external providers
    TEMPMAIL_API_KEY: str = ""

    @property
    def ai_enabled(self) -> bool:
        return (
            self.AI_PROVIDER not in ("", "none")
            and bool(self.AI_API_KEY)
            and bool(self.AI_MODEL)
        )


ai_settings = AISettings()
