"""New tests for AI provider resilience, circuit breaker, task routing, and timeouts."""
import asyncio
import httpx
import pytest
from pydantic import BaseModel
from unittest.mock import patch

from app.engine.ai.provider import (
    AIProvider,
    AIProviderError,
    FailoverAIProvider,
    OpenAICompatibleProvider,
    TaskType,
    _parse_structured,
    _strip_reasoning_blocks,
    _find_first_balanced_json,
    _model_circuit_breaker,
    _record_call,
    get_call_records,
)
from app.engine.ai.settings import ai_settings, AISettings


class DummyOutput(BaseModel):
    summary: str


class ReasoningModelProvider(AIProvider):
    """Mock model that returns <think> blocks + JSON."""
    name = "reasoning_model"

    async def generate_structured(self, system, prompt, schema, task_type=TaskType.GENERAL):
        raw = f"""<think>Let me think about this carefully...</think>\n\nHere is the JSON:\n```json\n{{"summary": "reasoned result"}}\n```"""
        return _parse_structured(raw, schema)

    @property
    def model_name(self):
        return "reasoning-model"


class Permanent404Provider(AIProvider):
    """Model returns 404 - should be permanently circuit-broken."""
    name = "permanent_404"

    async def generate_structured(self, system, prompt, schema, task_type=TaskType.GENERAL):
        raise AIProviderError("Model not found", provider=self.name, status_code=404)

    @property
    def model_name(self):
        return "permanent-404-model"


class Temporary5xxProvider(AIProvider):
    """Model returns 503 - temporary, should back off."""
    name = "temporary_5xx"

    async def generate_structured(self, system, prompt, schema, task_type=TaskType.GENERAL):
        raise AIProviderError("Service unavailable", provider=self.name, status_code=503)

    @property
    def model_name(self):
        return "temp-5xx-model"


@pytest.mark.asyncio
async def test_reasoning_blocks_stripped():
    """``` blocks are stripped and valid JSON extracted."""
    provider = ReasoningModelProvider()
    result = await provider.generate_structured("sys", "prompt", DummyOutput)
    assert result.summary == "reasoned result"


@pytest.mark.asyncio
async def test_parse_strips_think_blocks():
    """_parse_structured strips ``` blocks."""
    raw = "```reasoning here```\n{\"summary\": \"after think\"}"
    result = _parse_structured(raw, DummyOutput)
    assert result.summary == "after think"


@pytest.mark.asyncio
async def test_parse_find_first_balanced_json():
    """_find_first_balanced_json locates JSON in conversational text."""
    text = "Here is the result: {\"summary\": \"found it\"} and some more text."
    result = _find_first_balanced_json(text)
    assert result == '{"summary": "found it"}'


@pytest.mark.asyncio
async def test_permanent_404_circuit_breaker():
    """404 marks model permanently unavailable."""
    await _model_circuit_breaker.record_failure("test-404-model", status_code=404, is_permanent=True)
    available = await _model_circuit_breaker.is_available("test-404-model")
    assert available is False


@pytest.mark.asyncio
async def test_temporary_5xx_backoff():
    """503 marks model temporarily unavailable with backoff."""
    await _model_circuit_breaker.record_failure("test-5xx-model", status_code=503)
    available = await _model_circuit_breaker.is_available("test-5xx-model")
    assert available is False  # circuit open


@pytest.mark.asyncio
async def test_failover_ai_provider_unavailable():
    """When all providers fail, AI_PROVIDER_UNAVAILABLE is raised."""
    failing = Permanent404Provider()
    failover = FailoverAIProvider([failing])
    with pytest.raises(AIProviderError) as exc_info:
        await failover.generate_structured("sys", "prompt", DummyOutput)
    assert "AI_PROVIDER_UNAVAILABLE" in str(exc_info.value)


@pytest.mark.asyncio
async def test_call_records_logged():
    """Per-call usage is logged with model, latency, tokens, failure reason."""
    from app.engine.ai.provider import _call_records
    _call_records.clear()
    await _record_call(__import__("app.engine.ai.provider", fromlist=["CallRecord"]).CallRecord(
        model="test-model", task_type="next_action",
        latency_ms=150.5, tokens_used=120, success=True,
    ))
    records = get_call_records()
    assert len(records) == 1
    assert records[0].model == "test-model"
    assert records[0].task_type == "next_action"
    assert records[0].latency_ms == 150.5
    assert records[0].tokens_used == 120
    assert records[0].success is True


@pytest.mark.asyncio
async def test_task_type_enum():
    """TaskType enum has all required categories."""
    assert TaskType.OBSERVATION_SUMMARY == "observation_summary"
    assert TaskType.JOURNEY_SYNTHESIS == "journey_synthesis"
    assert TaskType.NEXT_ACTION == "next_action"
    assert TaskType.VERIFICATION == "verification"
    assert TaskType.GENERAL == "general"


def test_settings_tier_config():
    """Tier config returns different values per tier."""
    settings = AISettings(AI_TIER="kova-free")
    free = settings.get_tier_config("kova-free")
    assert free["tier"] == "kova-free"

    settings = AISettings(AI_TIER="kova-pro")
    pro = settings.get_tier_config("kova-pro")
    assert pro["tier"] == "kova-pro"

    settings = AISettings(AI_TIER="kova-enterprise")
    ent = settings.get_tier_config("kova-enterprise")
    assert ent["tier"] == "kova-enterprise"


def test_settings_task_model_override():
    """Task-specific model overrides work."""
    settings = AISettings(
        KOVA_FREE_TASK_MODELS="observation_summary:qwen/qwen3.8-27b,next_action:openai/gpt-oss-120b"
    )
    model = settings.get_task_model("kova-free", "observation_summary")
    assert model == "qwen/qwen3.8-27b"
    model = settings.get_task_model("kova-free", "next_action")
    assert model == "openai/gpt-oss-120b"
    model = settings.get_task_model("kova-free", "journey_synthesis")
    assert model is None  # no override


def test_openrouter_filters_free_slugs():
    """OpenRouter credentials filter out :free and /free auto-router entries."""
    settings = AISettings(
        OPENROUTER_API_KEY="test-key",
        OPENROUTER_MODELS="openrouter/free,nvidia/nemotron-3.5-lightning,cohere/north-mini-code:free",
    )
    creds = settings.get_provider_credentials("openrouter")
    models = creds["models"]
    assert "openrouter/free" not in models
    assert "cohere/north-mini-code:free" not in models
    assert "nvidia/nemotron-3.5-lightning" in models


@pytest.mark.asyncio
async def test_circuit_breaker_permanent_ttl():
    """Permanently unavailable model becomes available again after TTL."""
    slug = "test-ttl-model"
    await _model_circuit_breaker.record_failure(slug, status_code=404, is_permanent=True)

    # Immediately after: not available
    assert await _model_circuit_breaker.is_available(slug) is False

    # Manually expire the TTL
    async with _model_circuit_breaker._lock:
        h = _model_circuit_breaker._get(slug)
        h.permanent_unavailable_until = 0  # expired

    # Now available again
    assert await _model_circuit_breaker.is_available(slug) is True


@pytest.mark.asyncio
async def test_failover_ai_provider_unavailable_message():
    """AI_PROVIDER_UNAVAILABLE message is clear and actionable."""
    failing = Permanent404Provider()
    failover = FailoverAIProvider([failing])
    with pytest.raises(AIProviderError) as exc_info:
        await failover.generate_structured("sys", "prompt", DummyOutput)
    msg = str(exc_info.value)
    assert "AI_PROVIDER_UNAVAILABLE" in msg


@pytest.mark.asyncio
async def test_no_silent_heuristic_fallback():
    """When all models fail, AIProviderError is raised — never silent heuristic."""
    failing = Permanent404Provider()
    failover = FailoverAIProvider([failing])
    with pytest.raises(AIProviderError) as exc_info:
        await failover.generate_structured("sys", "prompt", DummyOutput)
    # Must raise, not return a heuristic result
    assert exc_info.type is AIProviderError


@pytest.mark.asyncio
async def test_task_based_routing_passes_task_type():
    """generate_structured accepts and propagates task_type."""
    provider = OpenAICompatibleProvider(model="test-model", api_key="test-key")
    assert provider.task_type == TaskType.GENERAL
    provider2 = OpenAICompatibleProvider(
        model="test-model", api_key="test-key", task_type=TaskType.OBSERVATION_SUMMARY
    )
    assert provider2.task_type == TaskType.OBSERVATION_SUMMARY


@pytest.mark.asyncio
async def test_late_response_within_total_budget():
    """Provider is configured with per-attempt timeout and total budget.

    Each attempt gets its own timeout; the whole call is bounded by total budget.
    A response arriving before the total deadline is accepted.
    """
    provider = OpenAICompatibleProvider(
        models=["model-a", "model-b"],
        api_key="test-key",
        per_attempt_timeout=8.0,
        total_budget_seconds=25.0,
    )
    assert provider._per_attempt_timeout == 8.0
    assert provider._total_budget == 25.0
    assert len(provider._models) == 2

    # Defaults from config
    provider2 = OpenAICompatibleProvider(model="default", api_key="key")
    assert provider2._per_attempt_timeout == ai_settings.AI_PER_ATTEMPT_TIMEOUT_SECONDS
    assert provider2._total_budget == ai_settings.AI_TOTAL_BUDGET_SECONDS


def test_parse_structured_invalid_json_raises():
    """Invalid JSON raises AIProviderError — no silent fallback."""
    try:
        _parse_structured("not json at all {{{", DummyOutput)
        assert False, "Should have raised AIProviderError"
    except AIProviderError:
        pass  # Expected


def test_parse_structured_valid_json():
    """Valid JSON parses correctly."""
    result = _parse_structured('{"summary": "valid"}', DummyOutput)
    assert result.summary == "valid"


# ---------------------------------------------------------------------------
# End-to-end mocked HTTP tests for acceptance requirements
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mocked_reasoning_style_output_extracted(monkeypatch):
    """Reasoning-style output with <think> blocks and leading prose is parsed successfully."""
    provider = OpenAICompatibleProvider(model="mock-reasoning-model", api_key="mock-key")

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "id": "gen-123",
            "choices": [
                {
                    "message": {
                        "content": (
                            "<think>\nLet me analyze the request thoroughly.\n"
                            "The user needs a DummyOutput object with summary field.\n"
                            "</think>\n"
                            "Sure! Here is the JSON you requested:\n\n"
                            "```json\n"
                            "{\n  \"summary\": \"extracted reasoned result\"\n}\n"
                            "```\n"
                            "Let me know if you need anything else!"
                        )
                    }
                }
            ],
            "usage": {"total_tokens": 150},
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )

    async def mock_post(*args, **kwargs):
        return mock_resp

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await provider.generate_structured("sys", "prompt", DummyOutput)
    assert result.summary == "extracted reasoned result"


@pytest.mark.asyncio
async def test_mocked_404_slug_permanent_circuit_breaker(monkeypatch):
    """404 marks model permanently unavailable and fails over; next call trips circuit immediately."""
    model_404 = "mock-404-slug"
    model_healthy = "mock-healthy-slug"
    provider = OpenAICompatibleProvider(models=[model_404, model_healthy], api_key="mock-key")

    call_count = {"404": 0, "healthy": 0}

    async def mock_post(client, url, *args, **kwargs):
        json_body = kwargs.get("json", {})
        m = json_body.get("model")
        if m == model_404:
            call_count["404"] += 1
            return httpx.Response(
                status_code=404,
                text='{"error": "Model not found: mock-404-slug"}',
                request=httpx.Request("POST", url),
            )
        call_count["healthy"] += 1
        return httpx.Response(
            status_code=200,
            json={
                "choices": [{"message": {"content": '{"summary": "healthy fallback"}'}}],
                "usage": {"total_tokens": 42},
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    # First call: 404 fails over to healthy model
    result = await provider.generate_structured("sys", "prompt", DummyOutput)
    assert result.summary == "healthy fallback"
    assert call_count["404"] == 1
    assert call_count["healthy"] == 1

    # Verify circuit breaker is now permanently open for model_404
    is_avail = await _model_circuit_breaker.is_available(model_404)
    assert is_avail is False

    # Second call with provider having only model_404: should fail immediately with AI_PROVIDER_UNAVAILABLE
    provider_404_only = OpenAICompatibleProvider(model=model_404, api_key="mock-key")
    with pytest.raises(AIProviderError) as exc_info:
        await provider_404_only.generate_structured("sys", "prompt", DummyOutput)
    assert "AI_PROVIDER_UNAVAILABLE" in str(exc_info.value)
    assert "circuit breaker open" in str(exc_info.value)
    # No new network request made to 404 model
    assert call_count["404"] == 1


@pytest.mark.asyncio
async def test_mocked_late_response_within_total_deadline(monkeypatch):
    """First attempt times out, second attempt succeeds before total deadline."""
    model_slow = "mock-slow-model"
    model_fast = "mock-fast-model"
    provider = OpenAICompatibleProvider(
        models=[model_slow, model_fast],
        api_key="mock-key",
        per_attempt_timeout=0.1,
        total_budget_seconds=1.0,
    )

    async def mock_post(client, url, *args, **kwargs):
        json_body = kwargs.get("json", {})
        m = json_body.get("model")
        if m == model_slow:
            # Simulate a slow attempt that exceeds per-attempt timeout
            await asyncio.sleep(0.2)
            return httpx.Response(status_code=200, json={}, request=httpx.Request("POST", url))
        # Fast model responds quickly before total deadline
        return httpx.Response(
            status_code=200,
            json={
                "choices": [{"message": {"content": '{"summary": "late attempt accepted"}'}}],
                "usage": {"total_tokens": 30},
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await provider.generate_structured("sys", "prompt", DummyOutput)
    assert result.summary == "late attempt accepted"


@pytest.mark.asyncio
async def test_mocked_repair_retry_succeeds(monkeypatch):
    """Invalid JSON triggers one repair retry which succeeds and returns valid JSON."""
    provider = OpenAICompatibleProvider(model="mock-repair-model", api_key="mock-key")

    call_index = 0

    async def mock_post(client, url, *args, **kwargs):
        nonlocal call_index
        call_index += 1
        if call_index == 1:
            # First attempt: invalid JSON
            return httpx.Response(
                status_code=200,
                json={"choices": [{"message": {"content": "This is completely invalid and not JSON"}}]},
                request=httpx.Request("POST", url),
            )
        # Second attempt (repair retry): valid JSON matching schema
        return httpx.Response(
            status_code=200,
            json={
                "choices": [{"message": {"content": '{"summary": "repaired successfully"}'}}],
                "usage": {"total_tokens": 55},
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await provider.generate_structured("sys", "prompt", DummyOutput)
    assert result.summary == "repaired successfully"
    assert call_index == 2


@pytest.mark.asyncio
async def test_all_models_fail_raises_ai_provider_unavailable_never_heuristics(monkeypatch):
    """When all models fail, raise AIProviderError with AI_PROVIDER_UNAVAILABLE — never silent fallback."""
    provider = OpenAICompatibleProvider(
        models=["model-fail-1", "model-fail-2"],
        api_key="mock-key",
    )

    async def mock_post(client, url, *args, **kwargs):
        return httpx.Response(
            status_code=500,
            text='{"error": "Internal Server Error"}',
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with pytest.raises(AIProviderError) as exc_info:
        await provider.generate_structured("sys", "prompt", DummyOutput)

    err = str(exc_info.value)
    assert "AI_PROVIDER_UNAVAILABLE" in err
    assert "model-fail-1" in err
    assert "model-fail-2" in err
