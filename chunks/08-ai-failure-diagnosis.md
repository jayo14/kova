# Chunk 08 — AI failure diagnosis (E) + report synthesis (H)

> Phase: **C — AI capabilities E, F, H + visual**
> Predecessors: `00-overview.md`, `01-productionize-agent-loop.md`
> Successors: none
> Estimated time: 1.5 days

---

## Goal & context

The brief (§5) defines two AI capabilities that the audit found are NOT actually using AI:

> *"E. Failure diagnosis: Correlate failed assertions, browser observations, screenshots, and network evidence to propose a plausible explanation."*
>
> *"H. Report synthesis: Translate raw execution evidence into clear findings, confidence levels, reproducible steps, and recommended investigations."*

The audit confirmed:
- `backend/app/modules/executions/reporting.py:46-66` `classify_failure` is a static dict lookup — maps error codes to categories. Not AI.
- `reporting.py:69-93` `diagnose_failure` returns `hypothesis: None` — no real diagnostic hypothesis is generated.
- `reporting.py:197-360` `ReportGenerator` is pure Jinja2 template + deterministic markdown rendering. No AI summarization.

So when Kova reports "Test failed: 500 internal server error", the user gets:
- ✅ A category (`network_or_application_server`)
- ✅ The error message
- ❌ A root-cause hypothesis ("the backend rejects the form because the email field is missing required validation")
- ❌ A confidence level
- ❌ A recommended next investigation step

**This chunk wires AI into failure diagnosis and report synthesis.** The `AgentReasoner` gets two new methods:
1. `propose_failure_hypothesis(execution_id, events, verification_checks)` → structured hypothesis with confidence + recommended investigation
2. `synthesize_report_summary(validation_report)` → human-readable 2-3 paragraph summary for the report's header

Both have heuristic fallbacks when AI is disabled.

This is Action 08 because the brief explicitly calls out "report synthesis" and "failure diagnosis" as AI capabilities — and they're currently the most visible "this is just a script" parts of the user experience.

---

## Files to touch

- `backend/app/engine/ai/reasoner.py` — add `propose_failure_hypothesis` and `synthesize_report_summary`
- `backend/app/engine/ai/schemas.py` — add `FailureHypothesis` and `ReportSummary` schemas
- `backend/app/modules/executions/reporting.py` — wire the new AI calls into `ReportGenerator`
- `backend/app/modules/validation/runner.py` — call `propose_failure_hypothesis` when a flow fails
- `backend/app/modules/executions/event_types.py` — add `FAILURE_HYPOTHESIS_PROPOSED`, `REPORT_SUMMARY_SYNTHESIZED`
- `backend/templates/validation_report.html` — render the AI hypothesis + summary prominently
- `backend/tests/unit/test_ai_diagnosis.py` — new
- `backend/tests/unit/test_report_synthesis.py` — new

---

## Step-by-step spec

1. **Define the schemas.** In `backend/app/engine/ai/schemas.py`:
   ```python
   class FailureHypothesis(BaseModel):
       root_cause: str                       # 1-2 sentence explanation of the likely root cause
       confidence: float                      # 0..1
       evidence_cited: list[str]              # which evidence IDs support this hypothesis
       alternative_explanations: list[str]   # other plausible causes, ranked
       recommended_investigation: str         # what the engineer should check next
       reproduction_steps: list[str]         # how to reproduce the failure
   
   class ReportSummary(BaseModel):
       headline: str                          # 1-sentence summary
       key_findings: list[str]                # 3-5 bullet points
       overall_assessment: str                # 1-paragraph narrative
       confidence: float                      # 0..1
       recommended_next_steps: list[str]      # actionable items for the engineer
   ```

2. **Add the reasoner methods.** In `backend/app/engine/ai/reasoner.py`:
   ```python
   async def propose_failure_hypothesis(
       self,
       execution_id: str,
       events: list[dict],
       verification_checks: list[dict],
       evidence_summary: dict,
   ) -> FailureHypothesis | None:
       """AI-driven failure diagnosis.
       
       Correlates failed assertions, browser observations, screenshots, and network
       evidence to propose a plausible root cause. Returns None if AI is unavailable.
       """
       if not self.provider:
           return self._heuristic_failure_hypothesis(events, verification_checks)
       
       # Filter to relevant events (failures, errors, network issues)
       failure_events = [e for e in events if "fail" in e.get("type", "").lower() or "error" in e.get("type", "").lower()]
       failed_checks = [c for c in verification_checks if c.get("verdict") == "failed"]
       
       system_prompt = (
           "You are diagnosing the root cause of a failed software validation run. "
           "Correlate the failed assertions, browser observations, and network evidence "
           "to propose the most plausible root cause. "
           "Cite specific evidence IDs in your hypothesis. "
           "If the evidence is insufficient to determine a root cause, say so explicitly — "
           "do not invent an explanation. "
           "Provide 1-2 alternative explanations ranked by likelihood. "
           "Recommend a concrete next investigation step."
       )
       user_prompt = json.dumps({
           "execution_id": execution_id,
           "failure_events": failure_events[:20],   # cap to keep prompt manageable
           "failed_verification_checks": failed_checks,
           "evidence_summary": {
               "screenshot_count": evidence_summary.get("screenshot_count", 0),
               "network_log_entries": evidence_summary.get("network_log_entries", [])[:10],
               "dom_snapshots": evidence_summary.get("dom_snapshot_count", 0),
               "console_errors": evidence_summary.get("console_errors", [])[:10],
           },
       }, default=str)[:6000]
       
       try:
           res = await self._provider.generate_structured(
               system=system_prompt,
               prompt=user_prompt,
               schema=FailureHypothesis,
           )
           return res
       except (AIProviderError, Exception) as e:
           logger.warning("propose_failure_hypothesis AI call failed: %s", e)
           return self._heuristic_failure_hypothesis(events, verification_checks)
   
   def _heuristic_failure_hypothesis(self, events, verification_checks) -> FailureHypothesis:
       """Conservative heuristic: cite the first failed check as the root cause."""
       failed = [c for c in verification_checks if c.get("verdict") == "failed"]
       if not failed:
           return FailureHypothesis(
               root_cause="No failed verification checks found; the failure may be environmental.",
               confidence=0.3,
               evidence_cited=[],
               alternative_explanations=[],
               recommended_investigation="Check the execution logs for unexpected errors.",
               reproduction_steps=[],
           )
       first_failure = failed[0]
       return FailureHypothesis(
           root_cause=f"Verification check '{first_failure.get('name', 'unknown')}' failed: {first_failure.get('reason', 'no reason provided')}",
           confidence=0.5,
           evidence_cited=first_failure.get("evidence_ids", []),
           alternative_explanations=["The check itself may be incorrectly specified"],
           recommended_investigation=f"Inspect the evidence linked to check '{first_failure.get('name')}' and verify the assertion is correct.",
           reproduction_steps=[],
       )
   
   async def synthesize_report_summary(
       self,
       validation_report: dict,
   ) -> ReportSummary | None:
       """AI-driven report synthesis for the human-readable summary section."""
       if not self.provider:
           return self._heuristic_report_summary(validation_report)
       
       system_prompt = (
           "You are writing a concise summary of a software validation report for an engineer. "
           "The summary should help the engineer quickly understand: "
           "(1) what was validated, (2) what passed, (3) what failed, (4) what to do next. "
           "Be specific and actionable. Avoid generic statements like 'investigate the issue'. "
           "Cite specific flows, evidence, or failure categories. "
           "If the validation passed cleanly, say so concisely."
       )
       user_prompt = json.dumps({
           "overall_status": validation_report.get("overall_status"),
           "flows_count": len(validation_report.get("results", [])),
           "passed_count": sum(1 for r in validation_report.get("results", []) if r.get("status") == "passed"),
           "failed_count": sum(1 for r in validation_report.get("results", []) if r.get("status") == "failed"),
           "unverified_count": sum(1 for r in validation_report.get("results", []) if r.get("status") == "unverified"),
           "failed_flows": [
               {"name": r.get("flow_name"), "failure_reason": r.get("failure_reason")}
               for r in validation_report.get("results", [])
               if r.get("status") == "failed"
           ][:5],
           "duration_seconds": validation_report.get("duration_ms", 0) / 1000,
       }, default=str)[:4000]
       
       try:
           res = await self._provider.generate_structured(
               system=system_prompt,
               prompt=user_prompt,
               schema=ReportSummary,
           )
           return res
       except (AIProviderError, Exception) as e:
           logger.warning("synthesize_report_summary AI call failed: %s", e)
           return self._heuristic_report_summary(validation_report)
   
   def _heuristic_report_summary(self, validation_report: dict) -> ReportSummary:
       """Deterministic summary when AI is unavailable."""
       results = validation_report.get("results", [])
       passed = sum(1 for r in results if r.get("status") == "passed")
       failed = sum(1 for r in results if r.get("status") == "failed")
       overall = validation_report.get("overall_status", "unknown")
       
       return ReportSummary(
           headline=f"Validation {overall}: {passed} passed, {failed} failed, {len(results)} total flows",
           key_findings=[
               f"Overall status: {overall}",
               f"Passed: {passed}/{len(results)}",
               f"Failed: {failed}/{len(results)}",
           ],
           overall_assessment=f"The validation run completed with overall status '{overall}'. See per-flow results for details.",
           confidence=0.7,
           recommended_next_steps=["Review the failed flows below for specific failure reasons."],
       )
   ```

3. **Wire into the validation runner.** In `backend/app/modules/validation/runner.py`, when a flow fails:
   ```python
   async def _record_flow_result(self, flow_result):
       if flow_result.status == "failed":
           # NEW: AI failure diagnosis
           reasoner = AgentReasoner(get_ai_provider())
           hypothesis = await reasoner.propose_failure_hypothesis(
               execution_id=str(flow_result.flow_id),
               events=flow_result.events,
               verification_checks=flow_result.verification_checks,
               evidence_summary=flow_result.evidence_summary,
           )
           if hypothesis:
               flow_result.hypothesis = hypothesis
               await self.event_recorder.record_event(
                   EventTypes.FAILURE_HYPOTHESIS_PROPOSED.value,
                   {"flow_id": str(flow_result.flow_id), "hypothesis": hypothesis.model_dump()},
               )
   ```

4. **Wire into the report generator.** In `backend/app/modules/executions/reporting.py`, in `ReportGenerator.generatevalidation_report`:
   ```python
   # After all flow results are aggregated
   reasoner = AgentReasoner(get_ai_provider())
   summary = await reasoner.synthesize_report_summary(validation_report.model_dump())
   if summary:
       validation_report.summary = summary
       await self.event_recorder.record_event(
           EventTypes.REPORT_SUMMARY_SYNTHESIZED.value,
           {"summary": summary.model_dump()},
       )
   ```

5. **Add the event types.** In `backend/app/modules/executions/event_types.py`:
   ```python
   FAILURE_HYPOTHESIS_PROPOSED = "ai.failure_hypothesis_proposed"
   REPORT_SUMMARY_SYNTHESIZED = "ai.report_summary_synthesized"
   ```

6. **Render in the report template.** In `backend/templates/validation_report.html`, add a prominent "AI Diagnosis" section at the top of each failed flow:
   ```html
   {% if flow.hypothesis %}
   <div class="ai-diagnosis">
       <h3>AI Diagnosis</h3>
       <p><strong>Root cause:</strong> {{ flow.hypothesis.root_cause }}</p>
       <p><strong>Confidence:</strong> {{ (flow.hypothesis.confidence * 100) | round }}%</p>
       {% if flow.hypothesis.evidence_cited %}
       <p><strong>Evidence cited:</strong> {{ flow.hypothesis.evidence_cited | join(", ") }}</p>
       {% endif %}
       {% if flow.hypothesis.alternative_explanations %}
       <p><strong>Alternative explanations:</strong></p>
       <ul>
           {% for alt in flow.hypothesis.alternative_explanations %}
           <li>{{ alt }}</li>
           {% endfor %}
       </ul>
       {% endif %}
       <p><strong>Recommended investigation:</strong> {{ flow.hypothesis.recommended_investigation }}</p>
       {% if flow.hypothesis.reproduction_steps %}
       <p><strong>Reproduction steps:</strong></p>
       <ol>
           {% for step in flow.hypothesis.reproduction_steps %}
           <li>{{ step }}</li>
           {% endfor %}
       </ol>
       {% endif %}
   </div>
   {% endif %}
   ```
   And add a summary section at the top of the report:
   ```html
   {% if validation_report.summary %}
   <div class="report-summary">
       <h2>{{ validation_report.summary.headline }}</h2>
       <p>{{ validation_report.summary.overall_assessment }}</p>
       <h3>Key findings</h3>
       <ul>
           {% for finding in validation_report.summary.key_findings %}
           <li>{{ finding }}</li>
           {% endfor %}
       </ul>
       <h3>Recommended next steps</h3>
       <ul>
           {% for step in validation_report.summary.recommended_next_steps %}
           <li>{{ step }}</li>
           {% endfor %}
       </ul>
   </div>
   {% endif %}
   ```

7. **Update the JSON report schema.** Extend `ValidationReport` (in `validation/schemas.py`) with:
   ```python
   class FlowValidationResult(BaseModel):
       # ... existing ...
       hypothesis: FailureHypothesis | None = None
   
   class ValidationReport(BaseModel):
       # ... existing ...
       summary: ReportSummary | None = None
   ```

8. **Write tests in `test_ai_diagnosis.py`:**
    - `test_propose_failure_hypothesis_with_ai` — mock provider returns a hypothesis; assert it's attached to the flow result
    - `test_propose_failure_hypothesis_heuristic_fallback` — AI disabled; assert the heuristic hypothesis is returned with `confidence=0.5`
    - `test_hypothesis_cites_evidence_ids` — assert the hypothesis references real evidence IDs from the events
    - `test_hypothesis_does_not_invent_evidence` — assert the AI's cited evidence IDs are a subset of the actual evidence IDs

9. **Write tests in `test_report_synthesis.py`:**
    - `test_synthesize_report_summary_with_ai` — mock provider returns a summary; assert it's attached to the report
    - `test_synthesize_report_summary_heuristic_fallback` — AI disabled; assert the heuristic summary is returned
    - `test_summary_headline_includes_overall_status` — assert the headline mentions the overall status
    - `test_summary_recommended_next_steps_are_actionable` — assert the steps are non-generic (not just "investigate the issue")

---

## Acceptance criteria

- [ ] `FailureHypothesis` and `ReportSummary` schemas exist with all required fields.
- [ ] `AgentReasoner.propose_failure_hypothesis` exists with AI + heuristic fallback.
- [ ] `AgentReasoner.synthesize_report_summary` exists with AI + heuristic fallback.
- [ ] `ValidationRunner` calls `propose_failure_hypothesis` when a flow fails; attaches the hypothesis to the result.
- [ ] `ReportGenerator` calls `synthesize_report_summary` and includes the summary in the report.
- [ ] HTML report template renders the AI Diagnosis section per failed flow and the Report Summary section at the top.
- [ ] `FAILURE_HYPOTHESIS_PROPOSED` and `REPORT_SUMMARY_SYNTHESIZED` event types exist and are emitted.
- [ ] Heuristic fallbacks work when AI is disabled — no crashes, no None values in the report.
- [ ] All 8 new tests pass.

---

## Anti-patterns to avoid

- **Do NOT let the AI invent evidence.** The hypothesis must cite real evidence IDs from the events list. If the AI proposes evidence that doesn't exist, that's a hallucination — the validator should reject it.
- **Do NOT present the hypothesis as definitive.** Always include the confidence level. The brief: "AI can synthesize the evidence into a useful explanation, but it must not manufacture evidence or present a speculative diagnosis as a confirmed fact."
- **Do NOT auto-apply the recommended investigation.** It's a suggestion for the engineer, not an automated action.
- **Do NOT make the heuristic fallback return `None`.** Always return a structured hypothesis — even if it's just "we couldn't determine the root cause." `None` would break the report rendering.
- **Do NOT call AI on every failed flow if there are 50+ failures.** Cap AI calls at the top 5 most important failures (by criticality). The rest get heuristic summaries.
- **Do NOT include sensitive data in the AI prompt.** Network logs and DOM snapshots may contain user data. Sanitize via the existing `RedactionFilter` before sending.
- **Do NOT log the full AI response at INFO level.** Use DEBUG. Hypotheses can be verbose.

---

## Dependencies & references

- **Read first:** `backend/app/modules/executions/reporting.py` (current `ReportGenerator`, `classify_failure`, `diagnose_failure`), `backend/app/modules/validation/runner.py`, `backend/app/engine/ai/reasoner.py` (existing methods for the pattern), `backend/templates/validation_report.html`.
- **Predecessor chunks:** `00-overview.md`, `01-productionize-agent-loop.md`.
- **Brief reference:** §5 capabilities E (Failure diagnosis) + H (Report synthesis); §4 Stage 7 (Evidence and reporting).
