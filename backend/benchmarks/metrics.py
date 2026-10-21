"""Benchmark metric definitions and evaluation formulas (§14)."""

from typing import Any
from pydantic import BaseModel, Field


class BenchmarkMetrics(BaseModel):
    # §14 metric 1: scenario relevance
    scenario_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    # §14 metric 2: true positive rate (defects detected / defects present)
    true_positive_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # §14 metric 3: false positive rate (correct behavior reported as failure)
    false_positive_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # §14 metric 4: false negative rate (real defects missed)
    false_negative_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # §14 metric 5: evidence quality (does the evidence support the diagnosis?)
    evidence_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    # §14 metric 6: manual intervention rate (how often the agent needed human takeover)
    manual_intervention_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # §14 metric 7: cost per useful validation
    cost_per_validation_usd: float = Field(default=0.0, ge=0.0)
    # §14 metric 8: time per useful validation
    time_per_validation_seconds: float = Field(default=0.0, ge=0.0)
    # §14 metric 9: model calls per validation
    model_calls_per_validation: float = Field(default=0.0, ge=0.0)

    # Real execution metrics (§Gap-Closing Prompt A)
    auth_success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    flow_completion_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_completeness: float = Field(default=1.0, ge=0.0, le=1.0)
    total_tokens: int = Field(default=0, ge=0)


def publish_benchmark_metrics(metrics: BenchmarkMetrics) -> None:
    """Emit the benchmark metrics to the Prometheus gauges defined in observability."""
    try:
        from app.observability.metrics import (
            benchmark_scenario_relevance,
            benchmark_true_positive_rate,
            benchmark_false_positive_rate,
            benchmark_false_negative_rate,
            benchmark_evidence_quality,
            benchmark_manual_intervention_rate,
            benchmark_cost_per_validation,
            benchmark_time_per_validation,
        )
        benchmark_scenario_relevance.set(metrics.scenario_relevance)
        benchmark_true_positive_rate.set(metrics.true_positive_rate)
        benchmark_false_positive_rate.set(metrics.false_positive_rate)
        benchmark_false_negative_rate.set(metrics.false_negative_rate)
        benchmark_evidence_quality.set(metrics.evidence_quality_score)
        benchmark_manual_intervention_rate.set(metrics.manual_intervention_rate)
        benchmark_cost_per_validation.set(metrics.cost_per_validation_usd)
        benchmark_time_per_validation.set(metrics.time_per_validation_seconds)
    except Exception:
        # Non-fatal if Prometheus registry is in a different lifecycle
        pass
