"""Unit tests for AI providers and failover mechanism."""

import pytest
from pydantic import BaseModel

from app.engine.ai.provider import (
    AIProvider,
    AIProviderError,
    FailoverAIProvider,
    OpenAICompatibleProvider,
    get_ai_provider,
)
from app.engine.ai.settings import AISettings


class DummyOutput(BaseModel):
    summary: str


class MockSuccessProvider(AIProvider):
    name = "mock_success"

    def __init__(self, model: str = "mock-model"):
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_structured(self, system: str, prompt: str, schema: type[DummyOutput]) -> DummyOutput:
        return schema(summary="mock_success_result")


class MockFailingProvider(AIProvider):
    name = "mock_failing"

    def __init__(self, status_code: int = 500):
        self.status_code = status_code

    @property
    def model_name(self) -> str:
        return "mock-failing-model"

    async def generate_structured(self, system: str, prompt: str, schema: type[DummyOutput]) -> DummyOutput:
        raise AIProviderError("Provider failed intentionally", provider=self.name, status_code=self.status_code)


@pytest.mark.asyncio
async def test_failover_first_success():
    prov1 = MockSuccessProvider("model-1")
    prov2 = MockSuccessProvider("model-2")
    failover = FailoverAIProvider([prov1, prov2])

    res = await failover.generate_structured("sys", "prompt", DummyOutput)
    assert res.summary == "mock_success_result"


@pytest.mark.asyncio
async def test_failover_skips_failed_and_succeeds_on_second():
    failing = MockFailingProvider(status_code=503)
    backup = MockSuccessProvider("backup-model")
    failover = FailoverAIProvider([failing, backup])

    res = await failover.generate_structured("sys", "prompt", DummyOutput)
    assert res.summary == "mock_success_result"


@pytest.mark.asyncio
async def test_failover_raises_when_all_fail():
    failing1 = MockFailingProvider(status_code=429)
    failing2 = MockFailingProvider(status_code=500)
    failover = FailoverAIProvider([failing1, failing2])

    with pytest.raises(AIProviderError) as exc_info:
        await failover.generate_structured("sys", "prompt", DummyOutput)
    assert "All AI providers in failover chain failed" in str(exc_info.value)


def test_ai_settings_disabled_when_empty():
    settings = AISettings(
        AI_PROVIDER="failover",
        GEMINI_API_KEY="",
        OPENROUTER_API_KEY="",
        GROQ_API_KEY="",
        NVIDIA_NIM_API_KEY="",
        AI_API_KEY="",
        AI_MODEL="",
    )
    assert settings.ai_enabled is False


def test_ai_settings_enabled_when_at_least_one_key():
    settings = AISettings(
        AI_PROVIDER="failover",
        GEMINI_API_KEY="test-gemini-key",
        OPENROUTER_API_KEY="",
        GROQ_API_KEY="",
        NVIDIA_NIM_API_KEY="",
    )
    assert settings.ai_enabled is True
    creds = settings.get_provider_credentials("gemini")
    assert creds is not None
    assert creds["api_key"] == "test-gemini-key"


def test_parse_structured_with_markdown_fences_and_thinking():
    provider = OpenAICompatibleProvider(model="test-model", api_key="test-key")

    # With think tags and markdown fence
    raw_output = "<think>The user wants a summary of the page</think>\n```json\n{\"summary\": \"Clean result\"}\n```"
    result = provider._parse_structured(raw_output, DummyOutput)
    assert result.summary == "Clean result"

    # Conversational wrapper around JSON object
    raw_conversational = "Here is the response requested:\n{\"summary\": \"Conversational\"}\nHope this helps!"
    result = provider._parse_structured(raw_conversational, DummyOutput)
    assert result.summary == "Conversational"

    # Direct JSON string
    result = provider._parse_structured('{"summary": "Direct"}', DummyOutput)
    assert result.summary == "Direct"

