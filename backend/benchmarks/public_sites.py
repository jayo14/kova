"""Read-only nightly reachability scorecard for publicly advertised test demos."""

import argparse
import asyncio
import time
from pathlib import Path

import httpx
import yaml

CONFIG = Path(__file__).parent / "fixtures" / "tier_b_public.yml"


async def run(output_prefix: str) -> None:
    targets = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or []
    results = []
    async with httpx.AsyncClient(
        timeout=15,
        follow_redirects=False,
        headers={"User-Agent": "Kova-Nightly-Test-Demo-Monitor/1.0"},
    ) as client:
        for target in targets:
            url = target["url"]
            if not url.startswith("https://") or not target.get("permission_source"):
                raise ValueError(f"Public benchmark target is not approved HTTPS: {target.get('id')}")
            started = time.perf_counter()
            try:
                response = await client.get(url)
                status = response.status_code
                outcome = "reachable" if status == 200 else "http_error"
            except httpx.HTTPError:
                status = None
                outcome = "unreachable"
            results.append({
                "site_id": target["id"],
                "url": url,
                "permission_source": target["permission_source"],
                "status_code": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "outcome": outcome,
            })

    payload = {"suite": "tier-b-public-read-only", "results": results}
    Path(f"{output_prefix}.json").write_text(
        __import__("json").dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Public demo site smoke results", "", "| Site | Status | Time (ms) | Outcome |", "|---|---:|---:|---|"]
    lines.extend(
        f"| {r['site_id']} | {r['status_code'] or 'N/A'} | {r['duration_ms']} | {r['outcome']} |"
        for r in results
    )
    Path(f"{output_prefix}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tier_b_public")
    args = parser.parse_args()
    asyncio.run(run(args.output))


if __name__ == "__main__":
    main()
