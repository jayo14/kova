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

    # "failover" | "openai_compatible" | "openrouter" | "gemini" | "groq" | "nvidia" | "none"
    AI_PROVIDER: str = "failover"
    AI_MODEL: str = ""
    AI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""       # alias/compat if AI_API_KEY is unset
    AI_BASE_URL: str = ""          # e.g. https://api.openai.com/v1 or a local gateway
    AI_TEMPERATURE: float = 0.2
    AI_TIMEOUT_SECONDS: float = 60.0
    AI_MAX_OUTPUT_TOKENS: int = 2000

    # Comma-separated list defining priority order, e.g. "openrouter,gemini,groq,nvidia"
    AI_FAILOVER_ORDER: str = "openrouter,gemini,groq,nvidia"

    # 1. Google Gemini (Best available model, single model without intra-provider fallback)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # 2. OpenRouter (Free models router & free tier models in descending order of quality & speed)
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODELS: str = "openrouter/free,nvidia/nemotron-3-super-120b-a12b:free,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,nvidia/nemotron-3.5-lightning:free,cohere/north-mini-code:free"
    OPENROUTER_MODEL: str = "openrouter/free"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # 3. Groq (Descending order of quality & speed)
    GROQ_API_KEY: str = ""
    GROQ_MODELS: str = "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b,allam-2-7b"
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # 4. NVIDIA NIM (Descending order of quality & speed)
    NVIDIA_NIM_API_KEY: str = ""
    NVIDIA_NIM_MODELS: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning,nvidia/nemotron-3.5-lightning-30b-a3b,meta/llama-3.2-11b-vision-instruct,openai/gpt-oss-20b"
    NVIDIA_NIM_MODEL: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # Temporary email integration
    TEMPMAIL_PROVIDER: str = "internal"   # reserved for future external providers
    TEMPMAIL_API_KEY: str = ""

    @property
    def failover_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.AI_FAILOVER_ORDER.split(",") if p.strip()]

    def get_provider_credentials(self, name: str) -> dict[str, any] | None:
        name_clean = name.strip().lower().replace("-", "_")
        if name_clean == "openrouter":
            raw_models = self.OPENROUTER_MODELS or self.OPENROUTER_MODEL
            models = [m.strip() for m in raw_models.split(",") if m.strip()]
            return {
                "name": "openrouter",
                "api_key": self.OPENROUTER_API_KEY,
                "models": models,
                "model": models[0] if models else "anthropic/claude-sonnet-4.5",
                "base_url": self.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1",
            }
        if name_clean in ("gemini", "google", "google_gemini"):
            # Gemini: Strictly single model without fallback. Quota exhaustion fails to next provider.
            model = self.GEMINI_MODEL.strip() if self.GEMINI_MODEL else "gemini-3.1-flash-lite"
            return {
                "name": "gemini",
                "api_key": self.GEMINI_API_KEY,
                "models": [model],
                "model": model,
                "base_url": self.GEMINI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/openai/",
            }
        if name_clean == "groq":
            raw_models = self.GROQ_MODELS or self.GROQ_MODEL
            models = [m.strip() for m in raw_models.split(",") if m.strip()]
            return {
                "name": "groq",
                "api_key": self.GROQ_API_KEY,
                "models": models,
                "model": models[0] if models else "openai/gpt-oss-120b",
                "base_url": self.GROQ_BASE_URL or "https://api.groq.com/openai/v1",
            }
        if name_clean in ("nvidia", "nvidia_nim", "nim"):
            raw_models = self.NVIDIA_NIM_MODELS or self.NVIDIA_NIM_MODEL
            models = [m.strip() for m in raw_models.split(",") if m.strip()]
            return {
                "name": "nvidia_nim",
                "api_key": self.NVIDIA_NIM_API_KEY,
                "models": models,
                "model": models[0] if models else "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                "base_url": self.NVIDIA_NIM_BASE_URL or "https://integrate.api.nvidia.com/v1",
            }
        if name_clean in ("openai_compatible", "custom", "openai", "fallback"):
            models = [m.strip() for m in self.AI_MODEL.split(",") if m.strip()]
            effective_key = self.AI_API_KEY or self.OPENAI_API_KEY
            return {
                "name": "openai_compatible",
                "api_key": effective_key,
                "models": models,
                "model": models[0] if models else "",
                "base_url": self.AI_BASE_URL or "https://api.openai.com/v1",
            }
        return None

    @property
    def effective_ai_key(self) -> str:
        return self.AI_API_KEY or self.OPENAI_API_KEY

    @property
    def ai_enabled(self) -> bool:
        if self.AI_PROVIDER in ("", "none", "disabled"):
            return False
        if self.AI_PROVIDER == "failover":
            for prov in self.failover_providers:
                creds = self.get_provider_credentials(prov)
                if creds and creds["api_key"] and creds["model"]:
                    return True
            return bool(self.effective_ai_key and (self.AI_MODEL or "gpt-4o-mini"))

        creds = self.get_provider_credentials(self.AI_PROVIDER)
        if creds:
            return bool(creds["api_key"] and creds["model"])
        return bool(self.effective_ai_key and (self.AI_MODEL or "gpt-4o-mini"))


def has_autonomous_execution_capability() -> bool:
    """Returns True only when an authoritative, usable reasoning path exists."""
    from app.config.settings import settings
    if ai_settings.AI_PROVIDER in ("", "none", "disabled"):
        return False
    return bool(settings.AGENT_EXECUTION_ENABLED or ai_settings.ai_enabled)


ai_settings = AISettings()
