"""Benchmark reporter producing JSON and Markdown summaries."""

from datetime import datetime, timezone
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

    # Real execution tracking (§Prompt A)
    auth_attempted: bool = False
    auth_success: bool = False
    flow_completed: bool = False
    evidence_completeness: float = 0.0
    tokens_used: int = 0


class BenchmarkReport(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
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

    @property
    def auth_success_rate(self) -> float:
        return self.metrics.auth_success_rate

    @property
    def flow_completion_rate(self) -> float:
        return self.metrics.flow_completion_rate

    @property
    def evidence_completeness(self) -> float:
        return self.metrics.evidence_completeness

    def to_markdown(self) -> str:
        m = self.metrics
        auth_icon = "✅" if m.auth_success_rate >= 0.95 else "❌"
        flow_icon = "✅" if m.flow_completion_rate >= 0.85 else "❌"
        tp_icon = "✅" if m.true_positive_rate >= 0.90 else "❌"
        fp_icon = "✅" if m.false_positive_rate <= 0.05 else "❌"
        eq_icon = "✅" if m.evidence_completeness >= 0.98 else "❌"
        sr_icon = "✅" if m.scenario_relevance >= 0.80 else "❌"
        cost_icon = "✅" if m.cost_per_validation_usd <= 0.05 else "ℹ️"
        time_icon = "✅" if m.time_per_validation_seconds <= 60.0 else "ℹ️"

        lines = [
            f"# Kova Benchmark Report — {self.timestamp.split()[0]}",
            "",
            f"**Suite:** {self.suite_name} | **Agent Mode:** {'Enabled (AI On)' if self.agent_enabled else 'Deterministic (AI Off)'}",
            "",
            "## Summary metrics",
            "| Metric | Value | Target | Status |",
            "|---|---|---|---|",
            f"| Scenario relevance | {m.scenario_relevance:.2f} | ≥0.80 | {sr_icon} |",
            f"| True positive rate | {m.true_positive_rate:.1%} | ≥90% | {tp_icon} |",
            f"| False positive rate | {m.false_positive_rate:.1%} | ≤5% | {fp_icon} |",
            f"| Evidence quality | {m.evidence_quality_score:.1%} | ≥98% | {eq_icon} |",
            f"| Auth success rate | {m.auth_success_rate:.1%} | ≥95% | {auth_icon} |",
            f"| Flow completion rate | {m.flow_completion_rate:.1%} | ≥85% | {flow_icon} |",
            f"| Evidence completeness | {m.evidence_completeness:.1%} | ≥98% | {eq_icon} |",
            f"| Cost per validation | ${m.cost_per_validation_usd:.4f} | ≤$0.05 | {cost_icon} |",
            f"| Time per validation | {m.time_per_validation_seconds:.2f}s | ≤60s | {time_icon} |",
            f"| Model calls per validation | {m.model_calls_per_validation:.1f} | N/A | ℹ️ |",
            "",
            "## Per-fixture results",
            "| Fixture | Expected | Detected | FP | Completed | Auth | Evidence | Notes |",
            "|---|---|---|---|---|---|---|---|",
        ]

        for r in self.fixture_results:
            auth_str = "N/A" if not r.auth_attempted else ("✅" if r.auth_success else "❌")
            comp_str = "✅" if r.flow_completed else "❌"
            ev_str = f"{r.evidence_completeness:.0%}"
            lines.append(
                f"| {r.fixture_id} | {r.expected_defects} | {r.detected_defects} | "
                f"{r.false_positives} | {comp_str} | {auth_str} | {ev_str} | {r.notes} |"
            )

        return "\n".join(lines) + "\n"
