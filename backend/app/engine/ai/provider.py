"""Provider-independent AI provider abstraction.

The AI layer is an untrusted *proposer*. Everything it returns is parsed into
explicit Pydantic schemas by the caller; raw text never becomes an executable
action. Providers must implement `generate_structured`, which requests a JSON
object conforming to a given Pydantic schema and raises `AIProviderError` on
any failure (invalid JSON, schema mismatch, network, timeout).

Kova never depends on a single lucky free model. Every configured model is
health-tracked with a circuit breaker. 404/"unavailable" marks a model
permanently unavailable for hours; 429/5xx backs off temporarily. Each attempt
gets its own timeout within a total budget, and every call is logged with
model, latency, tokens, and failure reason.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.engine.ai.settings import ai_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Task types for model routing
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    """Categories of AI calls so the cheapest adequate model is used per task."""

    OBSERVATION_SUMMARY = "observation_summary"
    JOURNEY_SYNTHESIS = "journey_synthesis"
    NEXT_ACTION = "next_action"
    VERIFICATION = "verification"
    GENERAL = "general"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AIProviderError(Exception):
    """Raised when the AI provider fails or returns unusable output."""

    def __init__(self, message: str, provider: str = "", status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Model health / circuit breaker
# ---------------------------------------------------------------------------

@dataclass
class ModelHealth:
    """Circuit-breaker state for a single model slug."""

    slug: str
    status: str = "healthy"  # healthy | temporarily_unavailable | permanently_unavailable
    failure_count: int = 0
    last_failure_time: float = 0.0
    circuit_open_until: float = 0.0
    permanent_unavailable_until: float = 0.0


class ModelCircuitBreaker:
    """Tracks per-model health and enforces circuit breaking."""

    # 404 / "unavailable" models stay out for 4 hours
    PERMANENT_TTL_SECONDS = 4 * 3600

    def __init__(self) -> None:
        self._health: dict[str, ModelHealth] = {}
        self._lock = asyncio.Lock()

    def _get(self, slug: str) -> ModelHealth:
        if slug not in self._health:
            self._health[slug] = ModelHealth(slug=slug)
        return self._health[slug]

    async def is_available(self, slug: str) -> bool:
        async with self._lock:
            h = self._get(slug)
            now = time.time()
            if h.status == "permanently_unavailable":
                if now < h.permanent_unavailable_until:
                    return False
                # TTL expired — give it another chance
                h.status = "healthy"
                h.failure_count = 0
                h.permanent_unavailable_until = 0.0
                return True
            if h.status == "temporarily_unavailable" and now < h.circuit_open_until:
                return False
            return True

    async def record_success(self, slug: str) -> None:
        async with self._lock:
            h = self._get(slug)
            h.status = "healthy"
            h.failure_count = 0
            h.circuit_open_until = 0.0

    LONG_LIVED_STATUS_CODES = {401, 403, 404}

    async def record_failure(
        self,
        slug: str,
        status_code: int | None = None,
        is_permanent: bool = False,
    ) -> None:
        async with self._lock:
            h = self._get(slug)
            h.failure_count += 1
            h.last_failure_time = time.time()

            # Only 401/403/404 (invalid key or model) or explicit is_permanent are long-lived
            if is_permanent or (status_code in self.LONG_LIVED_STATUS_CODES):
                h.status = "permanently_unavailable"
                h.permanent_unavailable_until = time.time() + self.PERMANENT_TTL_SECONDS
                logger.warning(
                    "Model '%s' marked long-lived unavailable (status=%s, circuit for %dh)",
                    slug, status_code, self.PERMANENT_TTL_SECONDS // 3600,
                )
                return

            # Temporary failure — 503/overloaded/429/timeouts/5xx (backoff 5 to 30s)
            if status_code == 429:
                backoff = min(30.0, max(5.0, 5.0 * (2 ** min(h.failure_count - 1, 3))))
            elif status_code == 503 or (status_code and 500 <= status_code < 600):
                backoff = min(30.0, max(5.0, 5.0 * (2 ** min(h.failure_count - 1, 3))))
            else:
                backoff = min(30.0, max(5.0, 5.0 * (2 ** min(h.failure_count - 1, 3))))

            h.circuit_open_until = time.time() + backoff
            h.status = "temporarily_unavailable"
            logger.warning(
                "Model '%s' temporarily unavailable (status=%s, backoff=%.1fs, failures=%d)",
                slug, status_code, backoff, h.failure_count,
            )

    async def snapshot(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return {
                slug: {
                    "status": h.status,
                    "failure_count": h.failure_count,
                    "last_failure_time": h.last_failure_time,
                    "circuit_open_until": h.circuit_open_until,
                    "permanent_unavailable_until": h.permanent_unavailable_until,
                }
                for slug, h in self._health.items()
            }


# Shared circuit breaker across all provider instances
_model_circuit_breaker = ModelCircuitBreaker()


# ---------------------------------------------------------------------------
# Per-call usage logging
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    """Per-call usage log for observability."""

    model: str
    task_type: str
    latency_ms: float
    tokens_used: int
    success: bool
    failure_reason: str | None = None
    status_code: int | None = None


_call_records: list[CallRecord] = []
_call_records_lock = asyncio.Lock()


async def _record_call(record: CallRecord) -> None:
    async with _call_records_lock:
        _call_records.append(record)
        if len(_call_records) > 10000:
            _call_records.pop(0)


def get_call_records() -> list[CallRecord]:
    return list(_call_records)


# ---------------------------------------------------------------------------
# Tolerant JSON extraction
# ---------------------------------------------------------------------------

def _strip_reasoning_blocks(text: str) -> str:
    """Strip reasoning blocks (<think>, <reasoning>, etc.) from model output."""
    text = re.sub(r"<think[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<reasoning[\s\S]*?</reasoning>", "", text, flags=re.IGNORECASE)
    # Also strip unclosed blocks if the model was cut off mid-thought
    text = re.sub(r"^<think[\s\S]*?(?:$|(?=\{))", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^<reasoning[\s\S]*?(?:$|(?=\{))", "", text, flags=re.IGNORECASE)
    return text.strip()


def _iter_balanced_json(text: str) -> list[str]:
    """Find all balanced JSON objects and arrays in text."""
    candidates: list[str] = []
    # Try JSON objects via brace scanning
    for start in range(len(text)):
        if text[start] != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    cand = text[start : i + 1]
                    try:
                        json.loads(cand)
                        candidates.append(cand)
                    except json.JSONDecodeError:
                        pass
                    break

    # Try JSON arrays
    for start in range(len(text)):
        if text[start] != "[":
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    cand = text[start : i + 1]
                    try:
                        json.loads(cand)
                        candidates.append(cand)
                    except json.JSONDecodeError:
                        pass
                    break

    return candidates


def _find_first_balanced_json(text: str) -> str | None:
    """Find the first balanced JSON object or array in text."""
    candidates = _iter_balanced_json(text)
    return candidates[0] if candidates else None


def _parse_structured(content: str, schema: type[T]) -> T:
    """Parse model text into a validated schema instance with tolerant extraction."""
    text = (content or "").strip()
    if not text:
        raise AIProviderError("AI returned empty content")

    # 1. Strip reasoning blocks
    text = _strip_reasoning_blocks(text)

    # 2. Try markdown code fences
    fence_matches = re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    for fm in fence_matches:
        cand = fm.group(1).strip()
        try:
            data = json.loads(cand)
            return schema.model_validate(data)
        except Exception:
            pass

    # 3. Try direct parse
    try:
        data = json.loads(text)
        return schema.model_validate(data)
    except Exception:
        pass

    # 4. Try balanced JSON object/array candidates
    for balanced in _iter_balanced_json(text):
        try:
            data = json.loads(balanced)
            return schema.model_validate(data)
        except Exception:
            pass

    raise AIProviderError(
        "AI returned invalid JSON that could not be parsed or validated",
    )


# ---------------------------------------------------------------------------
# Repair retry
# ---------------------------------------------------------------------------

async def _repair_retry(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
    system: str,
    prompt: str,
    schema: type[T],
    temperature: float,
    max_tokens: int,
    per_attempt_timeout: float,
) -> T | None:
    """One repair retry: ask the model to return only valid JSON matching the schema."""
    schema_json = json.dumps(schema.model_json_schema())
    repair_system = (
        f"{system}\n\n"
        f"Your previous response was invalid. Please return only valid JSON matching this schema, "
        f"with no reasoning blocks (<think>), no markdown fences, and no surrounding commentary:\n{schema_json}"
    )
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": repair_system},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = await asyncio.wait_for(
            client.post(f"{base_url}/chat/completions", headers=headers, json=payload),
            timeout=per_attempt_timeout,
        )
        if resp.status_code < 400:
            body = resp.json()
            choice = body["choices"][0]
            message = choice.get("message", {})
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            if not content.strip() and tool_calls:
                for tc in tool_calls:
                    func = tc.get("function") or {}
                    args = func.get("arguments")
                    if args and args.strip():
                        content = args
                        break
            if not content.strip():
                content = message.get("reasoning") or message.get("thought") or ""
            return _parse_structured(content, schema)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Model discovery from provider API
# ---------------------------------------------------------------------------

async def discover_models_from_endpoint(
    base_url: str,
    api_key: str,
    headers_extra: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> list[str]:
    """Query GET /models on a provider endpoint and return model IDs.

    Uses the API key to list all available models. Filters out :free auto-router
    entries (which pick unpredictable models) and non-chat models, returning
    explicit model IDs suitable for fallback lists.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    if headers_extra:
        headers.update(headers_extra)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        if resp.status_code != 200:
            return []
        data = resp.json()
        raw = data.get("data", [])
        if not isinstance(raw, list):
            return []
        ids = []
        for m in raw:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not mid or not isinstance(mid, str):
                continue
            # Filter out :free auto-router entries — use explicit model IDs only
            if ":free" in mid or "/free" in mid:
                continue
            # Check capabilities if provider returns supported_parameters (e.g. OpenRouter)
            supported = m.get("supported_parameters")
            if supported and isinstance(supported, list):
                if not any(p in supported for p in ("response_format", "tools", "tool_choice", "json")):
                    continue
            ids.append(mid)
        return ids
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Provider base
# ---------------------------------------------------------------------------

class AIProvider(ABC):
    """Base class for AI providers.

    Implementations are fully isolated behind this interface: swapping providers
    never touches the runtime, planner, or executor.
    """

    name: str = "base"
    total_tokens_used: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    model_calls: int = 0
    last_usage: dict[str, Any] = {}
    _last_success_time: float = 0.0
    _last_failure_time: float = 0.0
    _failure_count: int = 0

    async def is_available(self) -> bool:
        return True

    def get_usage(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens_used,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "model_calls": self.model_calls,
        }

    def reset_usage(self) -> None:
        self.total_tokens_used = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.model_calls = 0
        self.last_usage = {}

    @abstractmethod
    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        task_type: TaskType = TaskType.GENERAL,
    ) -> T:
        """Request a structured response conforming to `schema`.

        Raises AIProviderError on any failure. Returns a validated model instance.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(AIProvider):
    """Provider for any OpenAI-compatible chat completions API.

    Works with OpenAI, Azure OpenAI gateways, OpenRouter, Groq, NVIDIA NIM,
    Together, vLLM, Ollama, LM Studio, etc.

    Each model attempt gets its own timeout within a total budget. Models that
    return 404/unavailable are circuit-broken permanently (4h); 429/5xx backs
    off temporarily. On invalid JSON, one repair retry is attempted.
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str = "",
        base_url: str = "",
        name: str = "openai_compatible",
        models: list[str] | str | None = None,
        task_type: TaskType = TaskType.GENERAL,
        per_attempt_timeout: float | None = None,
        total_budget_seconds: float | None = None,
    ):
        raw_models: list[str] = []
        if models:
            if isinstance(models, str):
                raw_models = [m.strip() for m in models.split(",") if m.strip()]
            else:
                raw_models = [m.strip() for m in models if m.strip()]
        elif model:
            raw_models = [m.strip() for m in model.split(",") if m.strip()]

        if not raw_models or not api_key:
            raise AIProviderError(f"Provider {name} requires model(s) and api_key")

        self.name = name
        # Filter out :free auto-router — use explicit model IDs only
        self._models = [m for m in raw_models if ":free" not in m and "/free" not in m]
        if not self._models:
            self._models = raw_models  # fallback if everything was :free
        self._model = self._models[0]
        self._api_key = api_key
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._task_type = task_type

        # Per-attempt timeout and total budget from config with overrides
        self._per_attempt_timeout = (
            per_attempt_timeout if per_attempt_timeout is not None
            else ai_settings.AI_PER_ATTEMPT_TIMEOUT_SECONDS
        )
        self._total_budget = (
            total_budget_seconds if total_budget_seconds is not None
            else ai_settings.AI_TOTAL_BUDGET_SECONDS
        )

    @property
    def model_name(self) -> str:
        if len(self._models) == 1:
            return self._models[0]
        return f"{self._models[0]} (+{len(self._models) - 1} fallbacks: {', '.join(self._models[1:])})"

    @property
    def models(self) -> list[str]:
        return self._models

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def task_type(self) -> TaskType:
        return self._task_type

    @staticmethod
    def _parse_structured(content: str, schema: type[T]) -> T:
        return _parse_structured(content, schema)

    def get_models_for_task(self, task_type: TaskType | str) -> list[str]:
        """Order candidate models based on task type.

        Uses cheap fast models for observation summaries, and stronger models
        for journey synthesis, next-action decisions, and verification.
        Explicit task overrides in config take precedence.
        """
        task_name = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        override = ai_settings.get_task_model(ai_settings.AI_TIER, task_name)
        if override:
            if override in self._models:
                return [override] + [m for m in self._models if m != override]
            return [override] + list(self._models)

        if task_name == TaskType.OBSERVATION_SUMMARY.value:
            fast_keywords = ("lightning", "mini", "nano", "flash", "small", "lite", "7b", "8b")
            fast_models = [m for m in self._models if any(k in m.lower() for k in fast_keywords)]
            other_models = [m for m in self._models if m not in fast_models]
            if fast_models:
                return fast_models + other_models
            elif len(self._models) > 1:
                return [self._models[-1]] + self._models[:-1]

        return list(self._models)

    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        task_type: TaskType = TaskType.GENERAL,
    ) -> T:
        """Request a structured response conforming to `schema`.

        Tries each configured model in order, respecting the circuit breaker.
        Each attempt has its own timeout; the whole call is bounded by the
        total budget. On invalid JSON, one repair retry is attempted.
        """
        task_type = task_type or self._task_type
        models_to_try = self.get_models_for_task(task_type)
        schema_json = json.dumps(schema.model_json_schema())
        augmented_system = (
            f"{system}\n\n"
            f"You MUST respond ONLY with a single valid JSON object strictly conforming to this JSON Schema:\n"
            f"{schema_json}"
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter" in self.name.lower() or "openrouter.ai" in self._base_url:
            headers["HTTP-Referer"] = "https://kova.dev"
            headers["X-Title"] = "Kova Agent"

        errors: list[str] = []
        start_time = time.time()

        async with httpx.AsyncClient() as client:
            for idx, model in enumerate(models_to_try):
                # Check circuit breaker before attempting
                if not await _model_circuit_breaker.is_available(model):
                    errors.append(f"{model}: circuit breaker open")
                    continue

                # Enforce total budget — stop if we've used it all
                elapsed = time.time() - start_time
                if elapsed >= self._total_budget:
                    errors.append(f"{model}: total budget exhausted")
                    break
                remaining = self._total_budget - elapsed
                attempt_timeout = min(self._per_attempt_timeout, remaining)

                payload = {
                    "model": model,
                    "temperature": ai_settings.AI_TEMPERATURE,
                    "max_tokens": ai_settings.AI_MAX_OUTPUT_TOKENS,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": augmented_system},
                        {"role": "user", "content": prompt},
                    ],
                }

                call_start = time.perf_counter()
                try:
                    resp = await asyncio.wait_for(
                        client.post(
                            f"{self._base_url}/chat/completions",
                            headers=headers,
                            json=payload,
                        ),
                        timeout=attempt_timeout,
                    )
                except asyncio.TimeoutError:
                    err_msg = f"Timed out after {attempt_timeout:.1f}s"
                    logger.warning("Model '%s' timed out on '%s'.", model, self.name)
                    await _model_circuit_breaker.record_failure(model, status_code=None)
                    errors.append(f"{model}: {err_msg}")
                    await _record_call(CallRecord(
                        model=model, task_type=str(task_type),
                        latency_ms=(time.perf_counter() - call_start) * 1000,
                        tokens_used=0, success=False, failure_reason="timeout",
                    ))
                    continue
                except httpx.HTTPError as e:
                    err_detail = str(e) or repr(e) or type(e).__name__
                    err_msg = f"HTTP transport error ({type(e).__name__}): {err_detail}"
                    logger.warning("Model '%s' network error on '%s': %s", model, self.name, err_msg)
                    await _model_circuit_breaker.record_failure(model, status_code=None)
                    errors.append(f"{model}: {err_msg}")
                    await _record_call(CallRecord(
                        model=model, task_type=str(task_type),
                        latency_ms=(time.perf_counter() - call_start) * 1000,
                        tokens_used=0, success=False, failure_reason="network_error",
                    ))
                    continue

                latency_ms = (time.perf_counter() - call_start) * 1000

                if resp.status_code >= 400:
                    resp_text = resp.text[:250] if resp.text else ""
                    is_permanent = (
                        resp.status_code == 404
                        or "unavailable" in resp_text.lower()
                        or "not found" in resp_text.lower()
                        or "does not exist" in resp_text.lower()
                        or "no such model" in resp_text.lower()
                        or "deprecated" in resp_text.lower()
                        or "decommissioned" in resp_text.lower()
                    )
                    await _model_circuit_breaker.record_failure(
                        model, status_code=resp.status_code, is_permanent=is_permanent,
                    )
                    err_msg = f"HTTP {resp.status_code}: {resp_text}"
                    logger.warning("Model '%s' failed on '%s' (%s).", model, self.name, err_msg)
                    errors.append(f"{model}: {err_msg}")
                    await _record_call(CallRecord(
                        model=model, task_type=str(task_type),
                        latency_ms=latency_ms, tokens_used=0, success=False,
                        failure_reason=f"http_{resp.status_code}", status_code=resp.status_code,
                    ))
                    continue

                # Successful HTTP response — parse content
                try:
                    body = resp.json()
                    usage = body.get("usage") or {}
                    tokens_used = usage.get("total_tokens", 0) or (
                        usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                    )
                    self.last_usage = usage
                    self.total_prompt_tokens += usage.get("prompt_tokens", 0)
                    self.total_completion_tokens += usage.get("completion_tokens", 0)
                    self.total_tokens_used += tokens_used
                    self.model_calls += 1

                    choice = body["choices"][0]
                    message = choice.get("message", {})
                    content = message.get("content") or ""
                    tool_calls = message.get("tool_calls") or []
                    if not content.strip() and tool_calls:
                        for tc in tool_calls:
                            func = tc.get("function") or {}
                            args = func.get("arguments")
                            if args and args.strip():
                                content = args
                                break
                    # Some reasoning models put content in reasoning or thoughts if content is null/empty
                    if not content.strip():
                        content = message.get("reasoning") or message.get("thought") or ""

                    # Try to parse
                    try:
                        result = _parse_structured(content, schema)
                        await _model_circuit_breaker.record_success(model)
                        await _record_call(CallRecord(
                            model=model, task_type=str(task_type),
                            latency_ms=latency_ms, tokens_used=tokens_used, success=True,
                        ))
                        logger.info(
                            "AI call succeeded: model=%s task=%s latency=%.1fms tokens=%d",
                            model, task_type, latency_ms, tokens_used,
                        )
                        return result
                    except AIProviderError:
                        # One repair retry: ask model to return only valid JSON
                        repair_remaining = self._total_budget - (time.time() - start_time)
                        repaired = None
                        if repair_remaining > 0:
                            repaired = await _repair_retry(
                                client=client,
                                base_url=self._base_url,
                                headers=headers,
                                model=model,
                                system=system,
                                prompt=prompt,
                                schema=schema,
                                temperature=ai_settings.AI_TEMPERATURE,
                                max_tokens=ai_settings.AI_MAX_OUTPUT_TOKENS,
                                per_attempt_timeout=min(attempt_timeout, repair_remaining),
                            )
                        if repaired is not None:
                            await _model_circuit_breaker.record_success(model)
                            await _record_call(CallRecord(
                                model=model, task_type=str(task_type),
                                latency_ms=latency_ms, tokens_used=tokens_used, success=True,
                            ))
                            logger.info(
                                "AI call succeeded after repair: model=%s task=%s latency=%.1fms tokens=%d",
                                model, task_type, latency_ms, tokens_used,
                            )
                            return repaired
                        # Parse failed and repair failed — mark failure and continue
                        await _model_circuit_breaker.record_failure(model, status_code=None)
                        err_msg = "invalid JSON output"
                        errors.append(f"{model}: {err_msg}")
                        await _record_call(CallRecord(
                            model=model, task_type=str(task_type),
                            latency_ms=latency_ms, tokens_used=tokens_used,
                            success=False, failure_reason="invalid_json",
                        ))
                        logger.warning(
                            "AI call failed (invalid JSON): model=%s task=%s latency=%.1fms",
                            model, task_type, latency_ms,
                        )
                        continue

                except (KeyError, IndexError, ValueError) as e:
                    err_msg = f"Malformed AI response envelope: {e}"
                    logger.warning("Model '%s' envelope malformed on '%s': %s", model, self.name, err_msg)
                    await _model_circuit_breaker.record_failure(model, status_code=None)
                    errors.append(f"{model}: {err_msg}")
                    await _record_call(CallRecord(
                        model=model, task_type=str(task_type),
                        latency_ms=latency_ms, tokens_used=0, success=False,
                        failure_reason="malformed_envelope",
                    ))
                    continue

        # All models exhausted within budget
        raise AIProviderError(
            f"AI_PROVIDER_UNAVAILABLE: All models exhausted for provider '{self.name}': {'; '.join(errors)}",
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Failover provider (multiple providers)
# ---------------------------------------------------------------------------

class FailoverAIProvider(AIProvider):
    """Provider that wraps multiple AI providers with automatic fallback on failure."""

    name = "failover"

    def __init__(self, providers: list[AIProvider]):
        if not providers:
            raise AIProviderError("FailoverAIProvider requires at least one provider")
        self._providers = providers
        self._last_successful_provider: str | None = None

    @property
    def model_name(self) -> str:
        return f"failover({', '.join(f'{p.name}:{p.model_name}' for p in self._providers)})"

    @property
    def providers(self) -> list[AIProvider]:
        return self._providers

    @property
    def total_tokens_used(self) -> int:
        return sum(getattr(p, "total_tokens_used", 0) for p in self._providers)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(getattr(p, "total_prompt_tokens", 0) for p in self._providers)

    @property
    def total_completion_tokens(self) -> int:
        return sum(getattr(p, "total_completion_tokens", 0) for p in self._providers)

    @property
    def model_calls(self) -> int:
        return sum(getattr(p, "model_calls", 0) for p in self._providers)

    def reset_usage(self) -> None:
        for p in self._providers:
            p.reset_usage()

    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        task_type: TaskType = TaskType.GENERAL,
    ) -> T:
        errors: list[str] = []
        start_time = time.time()
        total_budget = ai_settings.AI_TOTAL_BUDGET_SECONDS

        # Order providers by recent success: prioritize the last working provider
        providers_to_try = list(self._providers)
        if self._last_successful_provider:
            providers_to_try.sort(
                key=lambda p: 0 if p.name == self._last_successful_provider else 1
            )

        for provider in providers_to_try:
            # Enforce total budget across providers
            elapsed = time.time() - start_time
            if elapsed >= total_budget:
                errors.append(f"{provider.name}: total budget exhausted")
                break

            # Skip open circuits quietly (debug level) if all models are unavailable
            if isinstance(provider, OpenAICompatibleProvider):
                models = provider.get_models_for_task(task_type)
                all_broken = True
                for m in models:
                    if await _model_circuit_breaker.is_available(m):
                        all_broken = False
                        break
                if all_broken:
                    logger.debug("Skipping provider '%s': all models circuit-broken", provider.name)
                    errors.append(f"{provider.name}: all models circuit-broken")
                    continue

            try:
                logger.info(
                    "Attempting AI generation with provider '%s' (models: %s)",
                    provider.name, provider.model_name,
                )
                try:
                    result = await provider.generate_structured(
                        system, prompt, schema, task_type=task_type
                    )
                except TypeError:
                    # Provider does not accept task_type kwarg — call without it
                    result = await provider.generate_structured(system, prompt, schema)

                # Record success to prioritize this provider for subsequent calls
                self._last_successful_provider = provider.name
                return result
            except AIProviderError as e:
                logger.warning(
                    "AI provider '%s' exhausted all options (status %s: %s). Failing over to next provider in chain...",
                    provider.name, getattr(e, "status_code", None), e,
                )
                errors.append(f"{provider.name}: {e}")
            except Exception as e:
                logger.warning(
                    "AI provider '%s' encountered unexpected error: %s. Failing over...",
                    provider.name, e,
                )
                errors.append(f"{provider.name}: {e}")

        raise AIProviderError(
            f"AI_PROVIDER_UNAVAILABLE: All AI providers in failover chain failed: {'; '.join(errors)}",
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

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
                if creds and creds["api_key"] and creds["models"]:
                    active_providers.append(
                        OpenAICompatibleProvider(
                            models=creds["models"],
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
        if creds and creds["api_key"] and creds["models"]:
            return OpenAICompatibleProvider(
                models=creds["models"],
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


def get_ai_provider_for_task(task_type: TaskType) -> AIProvider | None:
    """Return a provider configured for a specific task type.

    Task-based routing: observation summaries use a cheap fast model;
    journey synthesis, next-action, and verification use stronger models.
    Falls back to the default provider if no task-specific override exists.
    """
    provider = get_ai_provider()
    if provider is None:
        return None
    if isinstance(provider, OpenAICompatibleProvider):
        return OpenAICompatibleProvider(
            models=provider.models,
            api_key=provider._api_key,
            base_url=provider.base_url,
            name=provider.name,
            task_type=task_type,
            per_attempt_timeout=provider._per_attempt_timeout,
            total_budget_seconds=provider._total_budget,
        )
    return provider


def get_circuit_breaker_snapshot() -> dict[str, dict[str, Any]]:
    """Return current model health snapshot for observability."""
    # This is async; provide a sync wrapper for logging
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context — return empty, callers should use async version
        return {}
    except RuntimeError:
        return asyncio.run(_model_circuit_breaker.snapshot())


async def async_get_circuit_breaker_snapshot() -> dict[str, dict[str, Any]]:
    """Async version of circuit breaker snapshot."""
    return await _model_circuit_breaker.snapshot()
