"""Provider-independent AI provider abstraction.

The AI layer is an untrusted *proposer*. Everything it returns is parsed into
explicit Pydantic schemas by the caller; raw text never becomes an executable
action. Providers must implement `generate_structured`, which requests a JSON
object conforming to a given Pydantic schema and raises `AIProviderError` on
any failure (invalid JSON, schema mismatch, network, timeout).
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.engine.ai.settings import ai_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIProviderError(Exception):
    """Raised when the AI provider fails or returns unusable output."""

    def __init__(self, message: str, provider: str = "", status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class AIProvider(ABC):
    """Base class for AI providers.

    Implementations are fully isolated behind this interface: swapping providers
    never touches the runtime, planner, or executor.
    """

    name: str = "base"

    @abstractmethod
    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
    ) -> T:
        """Request a structured response conforming to `schema`.

        Raises AIProviderError on any failure. Returns a validated model instance.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(AIProvider):
    """Provider for any OpenAI-compatible chat completions API.

    Works with OpenAI, Azure OpenAI gateways, OpenRouter, Google Gemini,
    Groq, NVIDIA NIM, Together, vLLM, Ollama (with /v1), and LM Studio.
    Structured output is requested via response_format=json_object and validated
    locally against the Pydantic schema (portable across compatible providers).
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        name: str = "openai_compatible",
    ):
        if not model or not api_key:
            raise AIProviderError(f"Provider {name} requires model and api_key")
        self.name = name
        self._model = model
        self._api_key = api_key
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema())
        augmented_system = (
            f"{system}\n\n"
            f"You MUST respond ONLY with a single valid JSON object strictly conforming to this JSON Schema:\n"
            f"{schema_json}"
        )
        payload = {
            "model": self._model,
            "temperature": ai_settings.AI_TEMPERATURE,
            "max_tokens": ai_settings.AI_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": augmented_system},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter" in self.name.lower() or "openrouter.ai" in self._base_url:
            headers["HTTP-Referer"] = "https://kova.dev"
            headers["X-Title"] = "Kova Agent"

        try:
            async with httpx.AsyncClient(timeout=ai_settings.AI_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as e:
            raise AIProviderError(f"AI request timed out: {e}", provider=self.name) from e
        except httpx.HTTPError as e:
            raise AIProviderError(f"AI request failed: {e}", provider=self.name) from e

        if resp.status_code >= 400:
            err_msg = resp.text[:300] if resp.text else ""
            raise AIProviderError(
                f"AI provider returned {resp.status_code}: {err_msg}",
                provider=self.name,
                status_code=resp.status_code,
            )

        try:
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise AIProviderError(
                f"Malformed AI response envelope: {e}", provider=self.name
            ) from e

        return self._parse_structured(content, schema)

    def _parse_structured(self, content: str, schema: type[T]) -> T:
        """Parse model text into a validated schema instance. Fail-closed."""
        text = (content or "").strip()
        # Tolerate markdown fences around the JSON object
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIProviderError(
                f"AI returned invalid JSON: {e}", provider=self.name
            ) from e
        try:
            return schema.model_validate(data)
        except ValidationError as e:
            raise AIProviderError(
                f"AI output failed schema validation: {e.error_count()} error(s): "
                f"{e.errors()[:3]}",
                provider=self.name,
            ) from e


class FailoverAIProvider(AIProvider):
    """Provider that wraps multiple AI providers with automatic fallback on failure."""

    name = "failover"

    def __init__(self, providers: list[AIProvider]):
        if not providers:
            raise AIProviderError("FailoverAIProvider requires at least one provider")
        self._providers = providers

    @property
    def model_name(self) -> str:
        return f"failover({', '.join(f'{p.name}:{p.model_name}' for p in self._providers)})"

    @property
    def providers(self) -> list[AIProvider]:
        return self._providers

    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
    ) -> T:
        errors: list[str] = []
        for provider in self._providers:
            try:
                logger.info("Attempting AI generation with provider '%s' (model: %s)", provider.name, provider.model_name)
                result = await provider.generate_structured(system, prompt, schema)
                return result
            except AIProviderError as e:
                logger.warning(
                    "AI provider '%s' failed (status %s: %s). Falling over to next provider...",
                    provider.name,
                    getattr(e, "status_code", None),
                    e,
                )
                errors.append(f"{provider.name}: {e}")
            except Exception as e:
                logger.warning(
                    "AI provider '%s' encountered unexpected error: %s. Falling over...",
                    provider.name,
                    e,
                )
                errors.append(f"{provider.name}: {e}")

        raise AIProviderError(
            f"All AI providers in failover chain failed: {'; '.join(errors)}",
            provider=self.name,
        )


def get_ai_provider() -> AIProvider | None:
    """Return the configured provider or failover composite, or None when AI is disabled.

    Never raises at import/startup — a missing key means deterministic-only mode.
    """
    if not ai_settings.ai_enabled:
        return None
    try:
        if ai_settings.AI_PROVIDER == "failover":
            active_providers: list[AIProvider] = []
            for prov_name in ai_settings.failover_providers:
                creds = ai_settings.get_provider_credentials(prov_name)
                if creds and creds["api_key"] and creds["model"]:
                    active_providers.append(
                        OpenAICompatibleProvider(
                            model=creds["model"],
                            api_key=creds["api_key"],
                            base_url=creds["base_url"],
                            name=creds["name"],
                        )
                    )
            # Also check if generic AI_API_KEY is configured
            if ai_settings.AI_API_KEY and ai_settings.AI_MODEL:
                active_providers.append(
                    OpenAICompatibleProvider(
                        model=ai_settings.AI_MODEL,
                        api_key=ai_settings.AI_API_KEY,
                        base_url=ai_settings.AI_BASE_URL,
                        name="generic_fallback",
                    )
                )

            if not active_providers:
                return None
            if len(active_providers) == 1:
                return active_providers[0]
            return FailoverAIProvider(providers=active_providers)

        # Single provider mode
        creds = ai_settings.get_provider_credentials(ai_settings.AI_PROVIDER)
        if creds and creds["api_key"] and creds["model"]:
            return OpenAICompatibleProvider(
                model=creds["model"],
                api_key=creds["api_key"],
                base_url=creds["base_url"],
                name=creds["name"],
            )

        if ai_settings.AI_API_KEY and ai_settings.AI_MODEL:
            return OpenAICompatibleProvider(
                model=ai_settings.AI_MODEL,
                api_key=ai_settings.AI_API_KEY,
                base_url=ai_settings.AI_BASE_URL,
                name="openai_compatible",
            )

        logger.warning("Unknown or unconfigured AI_PROVIDER '%s' — AI layer disabled", ai_settings.AI_PROVIDER)
        return None
    except AIProviderError as e:
        logger.warning("AI provider init failed (%s) — AI layer disabled", e)
        return None
