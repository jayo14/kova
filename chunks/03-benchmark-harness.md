# Chunk 03 — §14 benchmark harness with the 6 required metrics

> Phase: **D — Benchmark harness**
> Predecessors: `01-productionize-agent-loop.md` (the benchmark exercises the agent loop)
> Successors: none
> Estimated time: 3 days

---

## Goal & context

The brief's §14 is the most concrete, measurable requirement in the entire document:

> *"Before expanding the feature set, Kova should establish a rigorous benchmark of representative applications and workflows. Measure:*
> - *Whether the AI generates relevant scenarios from product goals.*
> - *Whether the scenarios execute successfully when the application is functioning correctly.*
> - *Whether deliberate defects are detected.*
> - *How often correct behavior is incorrectly reported as a failure.*
> - *How often real defects are missed.*
> - *Whether evidence supports the reported diagnosis.*
> - *How often workflows require manual intervention.*
> - *How much time and model expenditure each useful validation requires.*
>
> *This benchmark should cover both known test cases and exploratory scenarios, with ground truth established wherever possible.*
>
> *It is the strongest way to distinguish real intelligence from impressive demonstrations."*

The audit confirmed **the benchmark harness does not exist.** Zero of the 6+ metrics are tracked. The only "benchmark" is `tests/integration/test_agent_benchmark.py`, a forgot-password E2E functional test, not a measurement framework.

**This chunk builds `backend/benchmarks/`** — a structured harness with:
1. A corpus of intentionally-buggy fixture apps with ground-truth defect labels
2. A runner that executes the agent against each fixture
3. Emitters for the 6+ required metrics
4. A CI job that gates regressions on these metrics

This is Action 03 (Phase D) because it's the brief's "strongest way to distinguish real intelligence from impressive demonstrations." Without it, every AI improvement is a vibe; with it, every improvement is a measured delta.

---

## Files to touch

- `backend/benchmarks/__init__.py` — new package
- `backend/benchmarks/fixtures/__init__.py`
- `backend/benchmarks/fixtures/buggy_contact_form/` — NEW fixture app (existing buggy-demo's contact-form bug, formalized)
- `backend/benchmarks/fixtures/buggy_auth_flow/` — NEW fixture (existing buggy-demo's auth bug, formalized)
- `backend/benchmarks/fixtures/working_contact_form/` — NEW fixture (same app, no bug — for false-positive measurement)
- `backend/benchmarks/fixtures/working_auth_flow/` — NEW fixture
- `backend/benchmarks/fixtures/permission_escalation/` — NEW fixture (teacher can access admin route — known defect)
- `backend/benchmarks/fixtures/visual_regression/` — NEW fixture (button shifted 50px off-canvas — known visual defect)
- `backend/benchmarks/fixtures/labels.yml` — ground-truth labels per fixture
- `backend/benchmarks/runner.py` — the benchmark runner
- `backend/benchmarks/metrics.py` — metric definitions and emitters
- `backend/benchmarks/reporter.py` — produces a JSON + Markdown report
- `backend/benchmarks/cli.py` — `python -m benchmarks.cli run --suite default`
- `backend/benchmarks/suites/default.py` — default benchmark suite
- `.github/workflows/benchmarks.yml` — CI job that runs the benchmark on every PR touching `engine/ai/` or `engine/execution/`
- `backend/app/observability/metrics.py` — add Prometheus counters for the 6 benchmark metrics
- `backend/tests/benchmarks/test_benchmark_runner.py` — test the harness itself

---

## Step-by-step spec

1. **Define the 6+ metrics.** In `backend/benchmarks/metrics.py`:
   ```python
   from pydantic import BaseModel
   
   class BenchmarkMetrics(BaseModel):
       # §14 metric 1: scenario relevance
       scenario_relevance: float           # 0..1 — fraction of generated scenarios that match ground-truth expected scenarios
       # §14 metric 2: true positive rate (defects detected / defects present)
       true_positive_rate: float           # 0..1
       # §14 metric 3: false positive rate (correct behavior reported as failure)
       false_positive_rate: float          # 0..1
       # §14 metric 4: false negative rate (real defects missed)
       false_negative_rate: float          # 0..1
       # §14 metric 5: evidence quality (does the evidence support the diagnosis?)
       evidence_quality_score: float       # 0..1 — judged by a separate evaluator
       # §14 metric 6: manual intervention rate (how often the agent needed human takeover)
       manual_intervention_rate: float     # 0..1 — fraction of runs that hit NEEDS_INPUT
       # §14 metric 7: cost per useful validation
       cost_per_validation_usd: float
       # §14 metric 8: time per useful validation
       time_per_validation_seconds: float
       # §14 metric 9: model calls per validation
       model_calls_per_validation: float
   ```

2. **Build the fixture corpus.** Each fixture is a small web app with known ground truth. Structure:
   ```
   benchmarks/fixtures/buggy_contact_form/
       app.py                  # the app
       ground_truth.yml        # defect labels
       expected_scenarios.yml  # scenarios the agent SHOULD generate
   ```
   
   Start with 5 fixtures:
   - **buggy_contact_form** — contact form returns 500 but UI shows success. Expected: agent detects the network failure and reports it as a defect.
   - **working_contact_form** — same UI, no bug. Expected: agent reports success. Used to measure false-positive rate.
   - **buggy_auth_flow** — login fails verification. Expected: agent detects the auth failure.
   - **permission_escalation** — teacher can access `/admin` route. Expected: agent discovers the privilege escalation.
   - **visual_regression** — a button is shifted 50px off-canvas. Expected: visual mode detects the layout defect.

3. **Write the ground-truth labels.** In `benchmarks/fixtures/buggy_contact_form/ground_truth.yml`:
   ```yaml
   fixture_id: buggy_contact_form
   description: Contact form reports UI success but POST /api/contact returns 500
   known_defects:
     - id: defect_1
       type: functional
       description: "POST /api/contact returns HTTP 500 while UI shows success message"
       location: "/contact"
       detection_method: network_response_inspection
       expected_severity: high
   expected_scenarios:
     - "Submit the contact form and verify the network response"
     - "Submit the contact form and verify the success message matches the network response"
   forbidden_scenarios: []
   ```

4. **Build the benchmark runner.** In `backend/benchmarks/runner.py`:
   ```python
   class BenchmarkRunner:
       def __init__(self, suite: BenchmarkSuite, agent_enabled: bool):
           self.suite = suite
           self.agent_enabled = agent_enabled
           self.results: list[BenchmarkResult] = []
       
       async def run(self) -> BenchmarkReport:
           for fixture in self.suite.fixtures:
               # Start the fixture app
               async with FixtureAppRunner(fixture) as app_url:
                   for scenario in fixture.expected_scenarios:
                       result = await self._run_validation(app_url, scenario)
                       self.results.append(result)
           return self._compute_report()
       
       async def _run_validation(self, app_url, scenario) -> BenchmarkResult:
           # Create a project, create a flow with objective=scenario, run the agent
           # Capture: outcome, evidence, model calls, time, cost
           # Compare against ground truth
           ...
       
       def _compute_report(self) -> BenchmarkReport:
           # Compute the 6+ metrics from the results
           ...
   ```

5. **Compute the metrics.**
   - `scenario_relevance` — for each fixture, compare the agent's generated scenarios against `expected_scenarios`. Use string similarity (or AI judge) to compute the fraction that match.
   - `true_positive_rate` — count fixtures where the agent reported a defect that matches a `known_defects` entry. Divide by total `known_defects`.
   - `false_positive_rate` — count fixtures where the agent reported a defect that is NOT in `known_defects`. Divide by total non-defect runs.
   - `false_negative_rate` — count `known_defects` the agent missed. Divide by total `known_defects`.
   - `evidence_quality_score` — for each reported defect, check whether the evidence (screenshot + network log + DOM) actually supports the diagnosis. Use a deterministic check (e.g. "network log shows the 500 response" → 1.0, else 0.0). For more nuanced cases, use a separate AI evaluator with a different prompt.
   - `manual_intervention_rate` — count runs that emitted `AGENT_LOOP_OUTCOME` with `status="NEEDS_INPUT"`.
   - `cost_per_validation_usd` — sum of `model_calls * cost_per_call` / useful validations.
   - `time_per_validation_seconds` — wall-clock time per validation.
   - `model_calls_per_validation` — count of AI provider invocations per validation.

6. **Build the reporter.** `backend/benchmarks/reporter.py` produces:
   - `benchmark_report.json` — full structured report
   - `benchmark_report.md` — human-readable summary table:
     ```markdown
     # Kova Benchmark Report — 2026-10-17
     
     ## Summary metrics
     | Metric | Value | Target | Status |
     |---|---|---|---|
     | Scenario relevance | 0.85 | ≥0.80 | ✅ |
     | True positive rate | 0.75 | ≥0.70 | ✅ |
     | False positive rate | 0.10 | ≤0.15 | ✅ |
     | False negative rate | 0.25 | ≤0.20 | ⚠️ |
     | Evidence quality | 0.90 | ≥0.85 | ✅ |
     | Manual intervention rate | 0.05 | ≤0.10 | ✅ |
     | Cost per validation | $0.023 | ≤$0.05 | ✅ |
     | Time per validation | 45s | ≤60s | ✅ |
     
     ## Per-fixture results
     | Fixture | Expected | Detected | False positive | False negative | Notes |
     |---|---|---|---|---|---|
     | buggy_contact_form | 1 | 1 | 0 | 0 | Network 500 detected via network_log inspection |
     | working_contact_form | 0 | 0 | 0 | 0 | Clean run |
     | buggy_auth_flow | 1 | 1 | 0 | 0 | Auth verification failure detected |
     | permission_escalation | 1 | 0 | 0 | 1 | Agent did not explore /admin route |
     | visual_regression | 1 | 0 | 0 | 1 | Visual mode not yet implemented (action 10) |
     ```

7. **Add the CLI.** `backend/benchmarks/cli.py`:
   ```python
   import argparse
   from benchmarks.runner import BenchmarkRunner
   from benchmarks.suites.default import DEFAULT_SUITE
   
   def main():
       parser = argparse.ArgumentParser()
       parser.add_argument("--suite", default="default")
       parser.add_argument("--agent", action="store_true", help="Use agent loop (action 01)")
       parser.add_argument("--output", default="benchmark_report")
       args = parser.parse_args()
       
       runner = BenchmarkRunner(suite=DEFAULT_SUITE, agent_enabled=args.agent)
       report = asyncio.run(runner.run())
       
       with open(f"{args.output}.json", "w") as f:
           f.write(report.json())
       with open(f"{args.output}.md", "w") as f:
           f.write(report.to_markdown())
   
   if __name__ == "__main__":
       main()
   ```
   Run: `python -m benchmarks.cli --agent --output /tmp/benchmark`

8. **Add Prometheus metrics.** In `backend/app/observability/metrics.py`:
   ```python
   benchmark_scenario_relevance = Gauge("kova_benchmark_scenario_relevance", "Scenario relevance score (0..1)")
   benchmark_true_positive_rate = Gauge("kova_benchmark_true_positive_rate", "TP rate (0..1)")
   benchmark_false_positive_rate = Gauge("kova_benchmark_false_positive_rate", "FP rate (0..1)")
   benchmark_false_negative_rate = Gauge("kova_benchmark_false_negative_rate", "FN rate (0..1)")
   benchmark_evidence_quality = Gauge("kova_benchmark_evidence_quality", "Evidence quality score (0..1)")
   benchmark_manual_intervention_rate = Gauge("kova_benchmark_manual_intervention_rate", "Manual intervention rate (0..1)")
   benchmark_cost_per_validation = Gauge("kova_benchmark_cost_per_validation_usd", "Cost per validation in USD")
   benchmark_time_per_validation = Gauge("kova_benchmark_time_per_validation_seconds", "Time per validation in seconds")
   ```
   The benchmark runner updates these gauges after each run.

9. **Add the CI job.** `.github/workflows/benchmarks.yml`:
   ```yaml
   name: Kova Benchmark
   on:
     pull_request:
       paths:
         - 'backend/app/engine/ai/**'
         - 'backend/app/engine/execution/**'
         - 'backend/app/modules/validation/**'
         - 'backend/benchmarks/**'
   jobs:
     benchmark:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: '3.12'
         - run: pip install -e backend/[dev]
         - run: playwright install chromium
         - run: python -m benchmarks.cli --agent --output /tmp/benchmark
           working-directory: backend
         - name: Check metric gates
           run: |
             python -c "
             import json
             r = json.load(open('/tmp/benchmark.json'))
             assert r.scenario_relevance >= 0.80, f'Scenario relevance {r.scenario_relevance} below 0.80'
             assert r.true_positive_rate >= 0.70, f'TP rate {r.true_positive_rate} below 0.70'
             assert r.false_positive_rate <= 0.15, f'FP rate {r.false_positive_rate} above 0.15'
             assert r.evidence_quality >= 0.85, f'Evidence quality {r.evidence_quality} below 0.85'
             print('All benchmark gates passed')
             "
         - name: Upload report
           uses: actions/upload-artifact@v4
           with:
             name: benchmark-report
             path: /tmp/benchmark.*
   ```

10. **Write tests for the harness itself.** `backend/tests/benchmarks/test_benchmark_runner.py`:
    - `test_benchmark_runner_runs_all_fixtures`
    - `test_metrics_computed_correctly`
    - `test_report_markdown_includes_all_metrics`
    - `test_known_defect_detected_in_buggy_contact_form`
    - `test_no_false_positive_in_working_contact_form`

---

## Acceptance criteria

- [ ] `backend/benchmarks/` package exists with `runner.py`, `metrics.py`, `reporter.py`, `cli.py`.
- [ ] At least 5 fixture apps exist with ground-truth labels in `labels.yml`.
- [ ] All 6+ §14 metrics are computed and emitted to Prometheus.
- [ ] `python -m benchmarks.cli --agent` runs end-to-end and produces JSON + Markdown reports.
- [ ] `.github/workflows/benchmarks.yml` runs on PRs touching AI/execution/validation code and gates on metric thresholds.
- [ ] The buggy_contact_form fixture is detected as a defect (TP).
- [ ] The working_contact_form fixture is NOT reported as a defect (no FP).
- [ ] All 5 harness tests pass.

---

## Anti-patterns to avoid

- **Do NOT use AI to judge AI without a deterministic fallback.** For `scenario_relevance` and `evidence_quality`, prefer deterministic checks (string matching, network-log inspection). Only use an AI evaluator for cases where deterministic checks can't apply, and document that choice.
- **Do NOT skip the working-contact-form fixture.** Without a "no defect" fixture, you can't measure false-positive rate. This is the most common benchmark-design mistake.
- **Do NOT make the benchmark suite too large.** 5 fixtures is enough to start. Adding more later is easy; the harness must be right first.
- **Do NOT gate the PR on every metric initially.** Start with `scenario_relevance >= 0.80` and `false_positive_rate <= 0.15`. Tighten thresholds as the agent improves.
- **Do NOT let the benchmark run for hours.** Each fixture should complete in <2 minutes. The whole suite should run in <10 minutes for CI usability.
- **Do NOT forget to mock the AI provider in CI.** Real API calls in CI are flaky and expensive. Use a mock provider that returns canned responses for known prompts.
- **Do NOT include benchmark fixtures in the production deployment.** They're test-only apps with intentional bugs. Ship them in the `benchmarks/` directory, not `examples/`.
- **Do NOT hide metric regressions.** If the benchmark shows a regression, the CI job must FAIL the PR. Don't make it informational only.

---

## Dependencies & references

- **Read first:** `backend/tests/integration/test_agent_benchmark.py` (the existing "benchmark" — understand what's there), `backend/tests/integration/test_buggy_demo.py` (existing fixture pattern), `examples/buggy-demo/server.py` (existing fixture app), `backend/app/observability/metrics.py` (Prometheus setup).
- **Predecessor chunks:** `01-productionize-agent-loop.md` (the benchmark exercises the agent loop).
- **Brief reference:** §14 "The immediate technical priority".
