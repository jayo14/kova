"""Command line interface for running the Kova benchmark harness (§14)."""

import argparse
import asyncio
import sys

from benchmarks.runner import BenchmarkRunner
from benchmarks.suites.default import DEFAULT_SUITE


def main():
    parser = argparse.ArgumentParser(description="Kova §14 Benchmark Runner")
    parser.add_argument("--suite", default="default", help="Benchmark suite name")
    parser.add_argument("--agent", action="store_true", help="Enable agent loop execution")
    parser.add_argument("--output", default="benchmark_report", help="Output file prefix")
    args = parser.parse_args()

    runner = BenchmarkRunner(suite=DEFAULT_SUITE, agent_enabled=args.agent)
    report = asyncio.run(runner.run())

    json_path = f"{args.output}.json"
    md_path = f"{args.output}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())

    print(f"Benchmark completed. Reports saved to {json_path} and {md_path}")
    print(report.to_markdown())


if __name__ == "__main__":
    main()
