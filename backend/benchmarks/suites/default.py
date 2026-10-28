"""Default benchmark suite (§14)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

from benchmarks.fixtures import FIXTURES_DIR


@dataclass
class FixtureDef:
    fixture_id: str
    description: str
    known_defects: list[dict[str, Any]]
    expected_scenarios: list[str]
    app_module: str
    path: Path
    app_factory: str | None = None


@dataclass
class BenchmarkSuite:
    name: str
    fixtures: list[FixtureDef] = field(default_factory=list)


def load_default_suite() -> BenchmarkSuite:
    suite = BenchmarkSuite(name="default")
    labels_file = FIXTURES_DIR / "labels.yml"
    if not labels_file.exists():
        return suite

    with open(labels_file, "r") as f:
        meta = yaml.safe_load(f)

    for item in meta.get("fixtures", []):
        f_id = item["id"]
        f_dir = FIXTURES_DIR / item["path"]
        gt_file = f_dir / "ground_truth.yml"
        sc_file = f_dir / "expected_scenarios.yml"

        gt_data = {}
        if gt_file.exists():
            with open(gt_file, "r") as f:
                gt_data = yaml.safe_load(f) or {}

        expected_scenarios = []
        if sc_file.exists():
            with open(sc_file, "r") as f:
                expected_scenarios = yaml.safe_load(f) or []

        suite.fixtures.append(
            FixtureDef(
                fixture_id=f_id,
                description=gt_data.get("description", item.get("name", "")),
                known_defects=gt_data.get("known_defects", []),
                expected_scenarios=expected_scenarios,
                app_module=f"benchmarks.fixtures.{item['path']}.app",
                path=f_dir,
            )
        )
    return suite


def load_messy_suite() -> BenchmarkSuite:
    """Load the local stress fixtures and their per-app proof/defect labels."""
    manifest = FIXTURES_DIR / "tier_a_messy.yml"
    with open(manifest, "r", encoding="utf-8") as stream:
        items = yaml.safe_load(stream) or []
    suite = BenchmarkSuite(name="tier-a-messy")
    for item in items:
        fixture_path = FIXTURES_DIR / item["path"]
        with open(fixture_path / "labels.yml", "r", encoding="utf-8") as stream:
            labels = yaml.safe_load(stream) or {}
        journeys = labels.get("journeys", [])
        suite.fixtures.append(
            FixtureDef(
                fixture_id=item["id"],
                description=labels.get("description", ""),
                known_defects=labels.get("planted_defects", []),
                expected_scenarios=[journey["name"] for journey in journeys],
                app_module="benchmarks.fixtures.messy_support",
                path=fixture_path,
                app_factory=item["factory"],
            )
        )
    return suite


DEFAULT_SUITE = load_default_suite()
