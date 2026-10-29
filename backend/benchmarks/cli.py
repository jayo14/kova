"""Command line interface for running the Kova benchmark harness (§14, Prompt A)."""

import argparse
import asyncio
from pathlib import Path

from benchmarks.runner import BenchmarkRunner
from benchmarks.suites.default import DEFAULT_SUITE, load_messy_suite


async def run_single_mode(agent_enabled: bool, output_prefix: str, suite_name: str) -> None:
    suite = load_messy_suite() if suite_name == "tier-a-messy" else DEFAULT_SUITE
    runner = BenchmarkRunner(suite=suite, agent_enabled=agent_enabled)
    report = await runner.run()

    json_path = f"{output_prefix}.json"
    md_path = f"{output_prefix}.md"
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)

    with open(json_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())

    mode_name = "AI Enabled" if agent_enabled else "Deterministic / AI Off"
    print(f"\n=======================================================")
    print(f"Benchmark completed [{mode_name}]. Saved to {json_path}")
    print(f"=======================================================\n")
    print(report.to_markdown())


def main():
    parser = argparse.ArgumentParser(description="Kova §14 Benchmark Runner")
    parser.add_argument("--suite", default="default", help="Benchmark suite name")
    parser.add_argument("--agent", action="store_true", help="Enable agent loop execution (AI on)")
    parser.add_argument("--both", action="store_true", help="Run both AI-off and AI-on modes and publish both")
    parser.add_argument("--output", default="benchmark_report", help="Output file prefix")
    args = parser.parse_args()
    if args.suite not in ("default", "tier-a-messy"):
        parser.error("suite must be 'default' or 'tier-a-messy'")

    if args.both:
        print("Running benchmark in dual mode (AI off and AI on)...")
        asyncio.run(run_single_mode(agent_enabled=False, output_prefix=f"{args.output}_ai_off", suite_name=args.suite))
        asyncio.run(run_single_mode(agent_enabled=True, output_prefix=f"{args.output}_ai_on", suite_name=args.suite))
    else:
        asyncio.run(run_single_mode(agent_enabled=args.agent, output_prefix=args.output, suite_name=args.suite))


if __name__ == "__main__":
    main()
