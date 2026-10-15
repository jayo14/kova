"""Diagnostic & model discovery script for Kova AI Providers.

Tests connections, queries available models, and validates structured completion
for Google Gemini, OpenRouter, Groq, and NVIDIA NIM.
"""

import asyncio
import json
import os
***REMOVED***
import time
from typing import Any

import httpx
from pydantic import BaseModel

# Ensure backend root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engine.ai.provider import FailoverAIProvider, OpenAICompatibleProvider, get_ai_provider
from app.engine.ai.settings import ai_settings


class ProbeResponse(BaseModel):
    provider: str
    status: str
    message: str


PROVIDERS = [
    {
        "id": "gemini",
        "name": "Google Gemini",
        "key_env": "GEMINI_API_KEY",
        "key_val": lambda: ai_settings.GEMINI_API_KEY,
        "model": lambda: ai_settings.GEMINI_MODEL,
        "base_url": lambda: ai_settings.GEMINI_BASE_URL.rstrip("/"),
        "models_url": lambda: f"{ai_settings.GEMINI_BASE_URL.rstrip('/')}/models",
        "headers": lambda k: {"Authorization": f"Bearer {k}"},
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "key_env": "OPENROUTER_API_KEY",
        "key_val": lambda: ai_settings.OPENROUTER_API_KEY,
        "model": lambda: ai_settings.OPENROUTER_MODEL,
        "base_url": lambda: ai_settings.OPENROUTER_BASE_URL.rstrip("/"),
        "models_url": lambda: f"{ai_settings.OPENROUTER_BASE_URL.rstrip('/')}/models",
        "headers": lambda k: {
            "Authorization": f"Bearer {k}",
            "HTTP-Referer": "https://kova.dev",
            "X-Title": "Kova Agent",
        },
    },
    {
        "id": "groq",
        "name": "Groq",
        "key_env": "GROQ_API_KEY",
        "key_val": lambda: ai_settings.GROQ_API_KEY,
        "model": lambda: ai_settings.GROQ_MODEL,
        "base_url": lambda: ai_settings.GROQ_BASE_URL.rstrip("/"),
        "models_url": lambda: f"{ai_settings.GROQ_BASE_URL.rstrip('/')}/models",
        "headers": lambda k: {"Authorization": f"Bearer {k}"},
    },
    {
        "id": "nvidia",
        "name": "NVIDIA NIM",
        "key_env": "NVIDIA_NIM_API_KEY",
        "key_val": lambda: ai_settings.NVIDIA_NIM_API_KEY,
        "model": lambda: ai_settings.NVIDIA_NIM_MODEL,
        "base_url": lambda: ai_settings.NVIDIA_NIM_BASE_URL.rstrip("/"),
        "models_url": lambda: f"{ai_settings.NVIDIA_NIM_BASE_URL.rstrip('/')}/models",
        "headers": lambda k: {"Authorization": f"Bearer {k}"},
    },
]


async def probe_provider(info: dict[str, Any]) -> dict[str, Any]:
    name = info["name"]
    creds = ai_settings.get_provider_credentials(info["id"])
    api_key = creds["api_key"].strip() if creds else ""
    models = creds["models"] if creds else []
    base_url = creds["base_url"] if creds else ""

    result = {
        "id": info["id"],
        "name": name,
        "key_env": info["key_env"],
        "has_key": bool(api_key),
        "models": models,
        "primary_model": models[0] if models else "",
        "status": "NOT CONFIGURED",
        "latency_ms": 0.0,
        "available_models": [],
        "sample_error": None,
    }

    if not api_key:
        result["status"] = "KEY MISSING"
        return result

    headers = info["headers"](api_key)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Fetch available models
        try:
            m_resp = await client.get(info["models_url"](), headers=headers)
            if m_resp.status_code == 200:
                data = m_resp.json()
                raw_models = data.get("data", [])
                if isinstance(raw_models, list):
                    model_ids = [m.get("id") for m in raw_models if isinstance(m, dict) and "id" in m]
                    result["available_models"] = sorted(model_ids)
            else:
                result["sample_error"] = f"Models list returned HTTP {m_resp.status_code}: {m_resp.text[:120]}"
        except Exception as e:
            result["sample_error"] = f"Models list error: {e}"

        # 2. Test structured chat completion probe with fallback list
        t0 = time.perf_counter()
        provider_instance = OpenAICompatibleProvider(
            models=models,
            api_key=api_key,
            base_url=base_url,
            name=name,
        )
        try:
            probe_out: ProbeResponse = await provider_instance.generate_structured(
                system="You are an AI probe validator. Reply with JSON conforming to the schema.",
                prompt=f"Confirm that provider {name} is operational.",
                schema=ProbeResponse,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result["latency_ms"] = round(elapsed_ms, 1)
            result["status"] = "ACTIVE & HEALTHY"
            result["probe_message"] = probe_out.message
        except Exception as e:
            result["status"] = "TEST FAILED"
            result["sample_error"] = str(e)

    return result


async def main():
    print("=" * 80)
    print("KOVA MULTI-PROVIDER AI DIAGNOSTIC & DISCOVERY TOOL")
    print("=" * 80)
    print(f"Active Provider Mode: {ai_settings.AI_PROVIDER}")
    print(f"Failover Order:       {ai_settings.AI_FAILOVER_ORDER}")
    print(f"AI Enabled:           {ai_settings.ai_enabled}\n")

    tasks = [probe_provider(p) for p in PROVIDERS]
    results = await asyncio.gather(*tasks)

    print(f"{'Provider':<16} | {'Key Env':<20} | {'Status':<18} | {'Latency':<9} | {'Configured Model'}")
    print("-" * 80)
    for r in results:
        lat = f"{r['latency_ms']}ms" if r['latency_ms'] > 0 else "-"
        fallbacks_str = f" (+{len(r['models'])-1} fallbacks)" if len(r['models']) > 1 else " (no fallback)"
        print(f"{r['name']:<16} | {r['key_env']:<20} | {r['status']:<18} | {lat:<9} | {r['primary_model']}{fallbacks_str}")
        if len(r['models']) > 1:
            print(f"   └─ Fallback Chain: {' -> '.join(r['models'])}")
        if r["sample_error"]:
            print(f"   └─ Error: {r['sample_error']}")
        if r["available_models"]:
            sample = r["available_models"][:8]
            more = len(r["available_models"]) - len(sample)
            print(f"   └─ Available models ({len(r['available_models'])} found): {', '.join(sample)}{f' (+{more} more)' if more > 0 else ''}")

    print("\n" + "=" * 80)
    print("FAILOVER PROVIDER TEST:")
    active = get_ai_provider()
    if active is None:
        print("  AI provider is currently inactive (no valid API keys provided yet).")
        print("  Add your API key(s) to `.env` or `backend/.env` and re-run this tool.")
    else:
        print(f"  Initialized AI Provider: {active.name} (model: {active.model_name})")
    print("=" * 80)


if __name__ == "__main__":
    # gated behind settings.DEBUG
    from app.config.settings import settings
    if not settings.DEBUG:
        print("Diagnostic scripts are dev-only and gated behind settings.DEBUG")
        sys.exit(1)
    asyncio.run(main())
