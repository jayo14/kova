"""Command line interface for running the Kova benchmark harness (§14, Prompt A)."""

import argparse
import asyncio
import sys

from benchmarks.runner import BenchmarkRunner
from benchmarks.suites.default import DEFAULT_SUITE


async def run_single_mode(agent_enabled: bool, output_prefix: str) -> None:
    runner = BenchmarkRunner(suite=DEFAULT_SUITE, agent_enabled=agent_enabled)
    report = await runner.run()

    json_path = f"{output_prefix}.json"
    md_path = f"{output_prefix}.md"

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

    if args.both:
        print("Running benchmark in dual mode (AI off and AI on)...")
        asyncio.run(run_single_mode(agent_enabled=False, output_prefix=f"{args.output}_ai_off"))
        asyncio.run(run_single_mode(agent_enabled=True, output_prefix=f"{args.output}_ai_on"))
    else:
        asyncio.run(run_single_mode(agent_enabled=args.agent, output_prefix=args.output))


if __name__ == "__main__":
    main()
