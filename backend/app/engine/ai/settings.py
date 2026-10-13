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
    AI_BASE_URL: str = ""          # e.g. https://api.openai.com/v1 or a local gateway
    AI_TEMPERATURE: float = 0.2
    AI_TIMEOUT_SECONDS: float = 60.0
    AI_MAX_OUTPUT_TOKENS: int = 2000

    # Comma-separated list defining priority order, e.g. "openrouter,gemini,groq,nvidia"
    AI_FAILOVER_ORDER: str = "openrouter,gemini,groq,nvidia"

    # 1. Google Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # 2. OpenRouter
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "anthropic/claude-3.5-sonnet"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # 3. Groq
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # 4. NVIDIA NIM
    NVIDIA_NIM_API_KEY: str = ""
    NVIDIA_NIM_MODEL: str = "meta/llama-3.3-70b-instruct"
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # Temporary email integration
    TEMPMAIL_PROVIDER: str = "internal"   # reserved for future external providers
    TEMPMAIL_API_KEY: str = ""

    @property
    def failover_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.AI_FAILOVER_ORDER.split(",") if p.strip()]

    def get_provider_credentials(self, name: str) -> dict[str, str] | None:
        name_clean = name.strip().lower().replace("-", "_")
        if name_clean == "openrouter":
            return {
                "name": "openrouter",
                "api_key": self.OPENROUTER_API_KEY,
                "model": self.OPENROUTER_MODEL or "anthropic/claude-3.5-sonnet",
                "base_url": self.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1",
            }
        if name_clean in ("gemini", "google", "google_gemini"):
            return {
                "name": "gemini",
                "api_key": self.GEMINI_API_KEY,
                "model": self.GEMINI_MODEL or "gemini-2.0-flash",
                "base_url": self.GEMINI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/openai/",
            }
        if name_clean == "groq":
            return {
                "name": "groq",
                "api_key": self.GROQ_API_KEY,
                "model": self.GROQ_MODEL or "llama-3.3-70b-versatile",
                "base_url": self.GROQ_BASE_URL or "https://api.groq.com/openai/v1",
            }
        if name_clean in ("nvidia", "nvidia_nim", "nim"):
            return {
                "name": "nvidia_nim",
                "api_key": self.NVIDIA_NIM_API_KEY,
                "model": self.NVIDIA_NIM_MODEL or "meta/llama-3.3-70b-instruct",
                "base_url": self.NVIDIA_NIM_BASE_URL or "https://integrate.api.nvidia.com/v1",
            }
        if name_clean in ("openai_compatible", "custom", "openai", "fallback"):
            return {
                "name": "openai_compatible",
                "api_key": self.AI_API_KEY,
                "model": self.AI_MODEL,
                "base_url": self.AI_BASE_URL or "https://api.openai.com/v1",
            }
        return None

    @property
    def ai_enabled(self) -> bool:
        if self.AI_PROVIDER in ("", "none"):
            return False
        if self.AI_PROVIDER == "failover":
            for prov in self.failover_providers:
                creds = self.get_provider_credentials(prov)
                if creds and creds["api_key"] and creds["model"]:
                    return True
            return bool(self.AI_API_KEY and self.AI_MODEL)

        creds = self.get_provider_credentials(self.AI_PROVIDER)
        if creds:
            return bool(creds["api_key"] and creds["model"])
        return bool(self.AI_API_KEY and self.AI_MODEL)


ai_settings = AISettings()
