"""Diagnostic & startup self-test for Kova AI Providers.

Runs one tiny JSON task per configured model and prints a pass/fail table.
If no model passes, exits with code 1 so deployment can fail loudly instead
of silently falling back to heuristics on a real site.

Usage:
    python scripts/diagnose_ai_providers.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx
from pydantic import BaseModel

# Ensure backend root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engine.ai.provider import (
    AIProviderError,
    FailoverAIProvider,
    OpenAICompatibleProvider,
    get_ai_provider,
    _model_circuit_breaker,
    TaskType,
)
from app.engine.ai.settings import ai_settings


class ProbeResponse(BaseModel):
    provider: str
    status: str
    message: str


async def probe_model(
    name: str,
    api_key: str,
    base_url: str,
    models: list[str],
    headers_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run one tiny JSON task against a single model. Returns pass/fail result."""
    result: dict[str, Any] = {
        "name": name,
        "models": models,
        "primary_model": models[0] if models else "",
        "status": "NOT CONFIGURED",
        "latency_ms": 0.0,
        "error": None,
        "passed": False,
    }

    if not api_key:
        result["status"] = "KEY MISSING"
        return result

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if headers_extra:
        headers.update(headers_extra)

    # Try each model in the fallback list
    for model in models:
        if not await _model_circuit_breaker.is_available(model):
            result["error"] = f"{model}: circuit breaker open"
            continue

        provider = OpenAICompatibleProvider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            name=name,
            per_attempt_timeout=8.0,
            total_budget_seconds=20.0,
        )
        t0 = time.perf_counter()
        try:
            probe_out: ProbeResponse = await provider.generate_structured(
                system="You are a health-check probe. Reply with JSON only.",
                prompt=f"Confirm that {name} model {model} is operational.",
                schema=ProbeResponse,
                task_type=TaskType.GENERAL,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result["latency_ms"] = round(elapsed_ms, 1)
            result["status"] = "PASS"
            result["passed"] = True
            result["probe_message"] = probe_out.message
            result["working_model"] = model
            return result
        except AIProviderError as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result["latency_ms"] = round(elapsed_ms, 1)
            result["error"] = str(e)
            result["status"] = "FAIL"
            continue
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result["latency_ms"] = round(elapsed_ms, 1)
            result["error"] = str(e)
            result["status"] = "FAIL"
            continue

    return result


async def main() -> int:
    """Run startup self-test. Returns 0 if at least one model passes, 1 otherwise."""
    print("=" * 80)
    print("KOVA AI STARTUP SELF-TEST")
    print("=" * 80)
    print(f"AI Provider Mode: {ai_settings.AI_PROVIDER}")
    print(f"AI Tier: {ai_settings.AI_TIER}")
    print(f"AI Enabled: {ai_settings.ai_enabled}")
    print()

    if not ai_settings.ai_enabled:
        print("SKIP: No AI provider configured. Deterministic-only mode.")
        print("=" * 80)
        return 0

    # Get configured providers
    providers_to_test = []
    if ai_settings.AI_PROVIDER == "failover":
        for prov_name in ai_settings.failover_providers:
            creds = ai_settings.get_provider_credentials(prov_name)
            if creds and creds["api_key"] and creds["models"]:
                providers_to_test.append({
                    "name": creds["name"],
                    "api_key": creds["api_key"],
                    "base_url": creds["base_url"],
                    "models": creds["models"],
                })
    else:
        creds = ai_settings.get_provider_credentials(ai_settings.AI_PROVIDER)
        if creds and creds["api_key"] and creds["models"]:
            providers_to_test.append({
                "name": creds["name"],
                "api_key": creds["api_key"],
                "base_url": creds["base_url"],
                "models": creds["models"],
            })

    if not providers_to_test:
        print("FAIL: No providers with API keys and models configured.")
        print("Set at least one of: OPENROUTER_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, NVIDIA_NIM_API_KEY")
        print("=" * 80)
        return 1

    # Run probes concurrently
    tasks = [
        probe_model(
            p["name"], p["api_key"], p["base_url"], p["models"],
            headers_extra={"HTTP-Referer": "https://kova.dev", "X-Title": "Kova Agent"}
            if "openrouter" in p["base_url"] else None,
        )
        for p in providers_to_test
    ]
    results = await asyncio.gather(*tasks)

    # Print results table
    print(f"{'Provider':<18} | {'Model':<45} | {'Status':<8} | {'Latency':<9} | {'Result'}")
    print("-" * 95)
    any_passed = False
    for r in results:
        lat = f"{r['latency_ms']}ms" if r['latency_ms'] > 0 else "-"
        model = r.get("working_model", r["primary_model"])
        status_icon = "✅" if r["passed"] else "❌"
        print(f"{r['name']:<18} | {model:<45} | {r['status']:<8} | {lat:<9} | {status_icon}")
        if r["error"]:
            print(f"{'':<18} |  └─ Error: {r['error'][:100]}")
        if r["passed"]:
            any_passed = True

    print()
    if any_passed:
        print("RESULT: At least one AI model is operational. ✅")
    else:
        print("RESULT: NO AI MODEL PASSED SELF-TEST. ❌")
        print("AI will be unavailable. Deployment should not proceed without at least one working model.")

    # Also test failover composite
    print()
    print("FAILOVER COMPOSITE TEST:")
    active = get_ai_provider()
    if active is None:
        print("  AI provider is inactive (no valid keys).")
    else:
        print(f"  Initialized: {active.name} (model: {active.model_name})")

    print("=" * 80)
    return 0 if any_passed else 1


if __name__ == "__main__":
    # gated behind settings.DEBUG unless run explicitly with --force
    from app.config.settings import settings

    force = "--force" in sys.argv
    if not settings.DEBUG and not force:
        print("Diagnostic scripts are dev-only. Use --force to run in production.")
        sys.exit(1)

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
