"""Benchmark reporter producing JSON and Markdown summaries."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

from benchmarks.metrics import BenchmarkMetrics


class FixtureRunResult(BaseModel):
    fixture_id: str
    expected_defects: int
    detected_defects: int
    false_positives: int
    false_negatives: int
    evidence_valid: bool
    needs_manual_intervention: bool
    duration_seconds: float
    model_calls: int
    cost_usd: float
    notes: str = ""


class BenchmarkReport(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    suite_name: str
    agent_enabled: bool
    metrics: BenchmarkMetrics
    fixture_results: list[FixtureRunResult] = Field(default_factory=list)

    # Convenience properties for direct metric checks
    @property
    def scenario_relevance(self) -> float:
        return self.metrics.scenario_relevance

    @property
    def true_positive_rate(self) -> float:
        return self.metrics.true_positive_rate

    @property
    def false_positive_rate(self) -> float:
        return self.metrics.false_positive_rate

    @property
    def false_negative_rate(self) -> float:
        return self.metrics.false_negative_rate

    @property
    def evidence_quality(self) -> float:
        return self.metrics.evidence_quality_score

    def to_markdown(self) -> str:
        m = self.metrics
        sr_icon = "✅" if m.scenario_relevance >= 0.80 else "❌"
        tp_icon = "✅" if m.true_positive_rate >= 0.70 else "❌"
        fp_icon = "✅" if m.false_positive_rate <= 0.15 else "❌"
        fn_icon = "✅" if m.false_negative_rate <= 0.20 else "⚠️"
        eq_icon = "✅" if m.evidence_quality_score >= 0.85 else "❌"
        mi_icon = "✅" if m.manual_intervention_rate <= 0.10 else "❌"
        cost_icon = "✅" if m.cost_per_validation_usd <= 0.05 else "⚠️"
        time_icon = "✅" if m.time_per_validation_seconds <= 60.0 else "⚠️"

        lines = [
            f"# Kova Benchmark Report — {self.timestamp.split()[0]}",
            "",
            f"**Suite:** {self.suite_name} | **Agent Mode:** {'Enabled' if self.agent_enabled else 'Heuristic/Deterministic'}",
            "",
            "## Summary metrics",
            "| Metric | Value | Target | Status |",
            "|---|---|---|---|",
            f"| Scenario relevance | {m.scenario_relevance:.2f} | ≥0.80 | {sr_icon} |",
            f"| True positive rate | {m.true_positive_rate:.2f} | ≥0.70 | {tp_icon} |",
            f"| False positive rate | {m.false_positive_rate:.2f} | ≤0.15 | {fp_icon} |",
            f"| False negative rate | {m.false_negative_rate:.2f} | ≤0.20 | {fn_icon} |",
            f"| Evidence quality | {m.evidence_quality_score:.2f} | ≥0.85 | {eq_icon} |",
            f"| Manual intervention rate | {m.manual_intervention_rate:.2f} | ≤0.10 | {mi_icon} |",
            f"| Cost per validation | ${m.cost_per_validation_usd:.3f} | ≤$0.05 | {cost_icon} |",
            f"| Time per validation | {m.time_per_validation_seconds:.1f}s | ≤60s | {time_icon} |",
            f"| Model calls per validation | {m.model_calls_per_validation:.1f} | N/A | ℹ️ |",
            "",
            "## Per-fixture results",
            "| Fixture | Expected | Detected | False positive | False negative | Notes |",
            "|---|---|---|---|---|---|",
        ]

        for r in self.fixture_results:
            lines.append(
                f"| {r.fixture_id} | {r.expected_defects} | {r.detected_defects} | "
                f"{r.false_positives} | {r.false_negatives} | {r.notes} |"
            )

        return "\n".join(lines) + "\n"
