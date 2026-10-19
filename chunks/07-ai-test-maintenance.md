# Chunk 07 — AI test-maintenance (capability F)

> Phase: **C — AI capabilities E, F, H + visual**
> Predecessors: `00-overview.md`, `01-productionize-agent-loop.md` (uses the agent loop)
> Successors: none
> Estimated time: 2 days

---

## Goal & context

The brief (§5 capability F + §4 Stage 8) is explicit:

> *"F. Test maintenance: When an interface changes, determine whether an existing locator or step can be updated without weakening the original acceptance criteria."*

And in Stage 8:

> *"When the application changes, Kova should be able to detect that a previously reliable workflow no longer matches the current interface or behavior, investigate the mismatch, and determine whether the scenario remains valid.*
>
> *The goal is not to blindly rewrite every broken test until it passes. An adaptive system must preserve the original acceptance criteria. Otherwise, it could silently change a test's meaning to accommodate a regression.*
>
> *A proposed repair should be evaluated against the intended behavior, and material changes should be recorded and reviewable."*

The audit found:
- `discovery/pipeline.py:163-226` has `rediscover(project_id, since=...)` that re-crawls stale pages. But it does NOT decide whether a flow's `success_condition` is still valid against the new page.
- `flow.status="stale"` is set externally (manually or by CI), not inferred from interface drift.
- Acceptance criteria are preserved at the Product Graph capability level (`product_graph/service.py:215`) but NOT at the Flow level.

**This chunk builds an AI test-maintenance step.** When `rediscover` detects that a flow's pages have changed locators (the buttons/selectors moved), the maintainer:
1. Re-evaluates the flow's `success_condition` against the new page state.
2. Either confirms the scenario is still valid (preserving the original criteria) OR flags `requires_review` with a concrete diff.
3. **Never auto-rewrites the acceptance criteria.** Material changes are recorded and surfaced for human review.

This is Action 07 because it's the brief's "continuous validation" loop — without it, Kova can detect that something changed but can't decide whether the change broke the test's meaning.

---

## Files to touch

- `backend/app/engine/ai/test_maintainer.py` — NEW; the AI test-maintenance step
- `backend/app/engine/ai/reasoner.py` — add `evaluate_scenario_validity(flow, new_page_state)` method
- `backend/app/engine/ai/schemas.py` — add `ScenarioValidityAssessment` schema
- `backend/app/engine/exploration/discovery/pipeline.py` — call the maintainer after `rediscover`
- `backend/app/modules/flows/service.py` — add `evaluate_stale_flows(project_id)` that flows through the maintainer
- `backend/app/modules/flows/models.py` — add `stale_reason: str | None`, `requires_review: bool`, `last_validated_against_graph_version: int | None`
- `backend/alembic/versions/0NN_add_flow_stale_fields.py` — migration
- `backend/app/api/routes/flows.py` — add `POST /api/v1/projects/{id}/flows:evaluate-stale`
- `backend/app/modules/executions/event_types.py` — add `FLOW_MARKED_STALE`, `FLOW_VALIDATED_AGAINST_NEW_GRAPH`
- `frontend/components/flows/mission-row.tsx` — render "Stale" + "Requires review" badges
- `frontend/components/flows/mission-detail-header.tsx` — show the staleness reason + diff
- `backend/tests/unit/test_test_maintainer.py` — new

---

## Step-by-step spec

1. **Define the schema.** In `backend/app/engine/ai/schemas.py`:
   ```python
   class ScenarioValidityAssessment(BaseModel):
       flow_id: str
       is_still_valid: bool                  # True if the success_condition can still be checked against the new page
       confidence: float                     # 0..1 — how confident the AI is in its assessment
       changes_detected: list[str]           # human-readable list of locator/structure changes
       acceptance_criteria_impacted: list[str]  # which criteria are affected
       requires_review: bool                 # True if a material change requires human sign-off
       proposed_locator_updates: list[dict]  # suggested new selectors — NEVER auto-applied
       reasoning: str
   ```

2. **Add the reasoner method.** In `backend/app/engine/ai/reasoner.py`:
   ```python
   async def evaluate_scenario_validity(
       self,
       flow: dict,                           # the existing Flow
       new_page_state: dict,                 # what the page looks like now (from rediscover)
       original_graph_version: int,          # the Product Graph version when the flow was last validated
   ) -> ScenarioValidityAssessment | None:
       """AI-driven assessment of whether a stale flow is still valid.
       
       The AI inspects:
       - The flow's success_condition (the original acceptance criteria)
       - The new page state (current DOM, locators, available actions)
       - The original page state (from the graph snapshot at original_graph_version)
       
       Returns an assessment. NEVER modifies the flow — proposes updates only.
       """
       if not self.provider:
           return self._heuristic_validity_assessment(flow, new_page_state)
       
       system_prompt = (
           "You are evaluating whether an existing test scenario is still valid "
           "after the application's interface has changed. "
           "Your job: determine whether the original acceptance criteria can still be "
           "checked against the new page state. "
           "DO NOT propose changes to the acceptance criteria themselves — only to "
           "the locators/selectors used to check them. "
           "If the criteria can no longer be checked (e.g. the feature was removed), "
           "mark is_still_valid=false and requires_review=true. "
           "If the locators moved but the feature is intact, propose updated locators "
           "with high confidence. "
           "Never propose weakening the criteria to make the test pass."
       )
       user_prompt = json.dumps({
           "flow_objective": flow.get("objective"),
           "flow_success_condition": flow.get("success_condition"),
           "flow_steps_summary": [{"type": s.get("type"), "target": s.get("target")} for s in flow.get("steps", [])],
           "new_page_state": {
               "url": new_page_state.get("url"),
               "available_buttons": new_page_state.get("buttons", []),
               "available_forms": new_page_state.get("forms", []),
               "current_locators_for_original_steps": new_page_state.get("locator_matches", []),
           },
           "original_graph_version": original_graph_version,
       }, default=str)[:6000]
       
       try:
           res = await self._provider.generate_structured(
               system=system_prompt,
               prompt=user_prompt,
               schema=ScenarioValidityAssessment,
           )
           return res
       except (AIProviderError, Exception) as e:
           logger.warning("evaluate_scenario_validity AI call failed: %s", e)
           return self._heuristic_validity_assessment(flow, new_page_state)
   
   def _heuristic_validity_assessment(self, flow: dict, new_page_state: dict) -> ScenarioValidityAssessment:
       """Conservative heuristic: if any locator from the original flow is missing
       in the new page state, mark as requires_review."""
       original_steps = flow.get("steps", [])
       new_locator_matches = new_page_state.get("locator_matches", [])
       missing_locators = [
           s for s in original_steps
           if s.get("type") in ("click", "input", "select")
           and not any(m.get("original_target") == s.get("target") for m in new_locator_matches)
       ]
       return ScenarioValidityAssessment(
           flow_id=flow.get("id", ""),
           is_still_valid=len(missing_locators) == 0,
           confidence=0.5,
           changes_detected=[f"Locator for step '{s.get('description', s.get('type'))}' not found in new page" for s in missing_locators],
           acceptance_criteria_impacted=[] if not missing_locators else ["Locators required to check criteria are missing"],
           requires_review=len(missing_locators) > 0,
           proposed_locator_updates=[],
           reasoning="Heuristic assessment: missing locators detected; cannot verify criteria without human review.",
       )
   ```

3. **Build the maintainer.** In `backend/app/engine/ai/test_maintainer.py`:
   ```python
   from app.engine.ai.reasoner import AgentReasoner
   from app.engine.ai.schemas import ScenarioValidityAssessment
   from app.modules.product_graph.repository import ProductGraphRepository
   from app.modules.flows.repository import FlowRepository
   
   class TestMaintainer:
       def __init__(self, reasoner: AgentReasoner, pg_repo: ProductGraphRepository, flow_repo: FlowRepository):
           self.reasoner = reasoner
           self.pg_repo = pg_repo
           self.flow_repo = flow_repo
   
       async def evaluate_stale_flow(self, flow_id: uuid.UUID) -> ScenarioValidityAssessment:
           """Re-evaluate a single flow against the current Product Graph."""
           flow = await self.flow_repo.get_by_id(flow_id)
           if not flow:
               raise ValueError(f"Flow {flow_id} not found")
           
           # Get the current page state from the graph (post-rediscover)
           current_pages = await self.pg_repo.get_pages_for_flow(flow_id)
           new_page_state = self._build_page_state_snapshot(current_pages)
           
           # Get the original graph version
           original_version = flow.last_validated_against_graph_version or 0
           
           # AI assessment
           assessment = await self.reasoner.evaluate_scenario_validity(
               flow={
                   "id": str(flow.id),
                   "objective": flow.objective,
                   "success_condition": flow.success_condition,
                   "steps": flow.steps or [],
               },
               new_page_state=new_page_state,
               original_graph_version=original_version,
           )
           
           # Update the flow row (NEVER modify success_condition — only metadata)
           await self.flow_repo.update(flow_id, {
               "stale_reason": "; ".join(assessment.changes_detected) if assessment.changes_detected else None,
               "requires_review": assessment.requires_review,
               "last_validated_against_graph_version": await self.pg_repo.get_current_version(flow.project_id),
           })
           
           return assessment
   ```

4. **Wire into `rediscover`.** In `backend/app/engine/exploration/discovery/pipeline.py`, after `rediscover` completes the re-crawl:
   ```python
   async def rediscover(self, project_id, since=None):
       # ... existing re-crawl logic ...
       
       # NEW: evaluate stale flows against the new graph
       from app.engine.ai.test_maintainer import TestMaintainer
       from app.engine.ai.reasoner import AgentReasoner
       from app.engine.ai.provider import get_ai_provider
       
       reasoner = AgentReasoner(get_ai_provider())
       maintainer = TestMaintainer(reasoner, self.repo, FlowRepository(self.db_session))
       
       flows = await self.flow_repo.list_by_project(project_id)
       for flow in flows:
           if flow.last_validated_against_graph_version and flow.last_validated_against_graph_version < new_graph_version:
               assessment = await maintainer.evaluate_stale_flow(flow.id)
               if assessment.requires_review:
                   # Emit event for the user
                   await self._emit_event("flow.requires_review", {
                       "flow_id": str(flow.id),
                       "changes": assessment.changes_detected,
                       "reasoning": assessment.reasoning,
                   })
   ```

5. **Add the API endpoint.** In `backend/app/api/routes/flows.py`:
   ```python
   @router.post("/projects/{project_id}/flows:evaluate-stale")
   async def evaluate_stale_flows(
       project_id: uuid.UUID,
       user: User = Depends(get_current_user),
       db: AsyncSession = Depends(get_db),
   ):
       """Re-evaluate all stale flows in a project against the current Product Graph."""
       # Verify ownership
       # Call TestMaintainer.evaluate_stale_flow for each flow marked stale
       # Return a summary: {evaluated: N, still_valid: M, requires_review: K, assessments: [...]}
   ```

6. **Add the migration.** `0NN_add_flow_stale_fields.py`:
   - Add `stale_reason: Text | None` to `flows`
   - Add `requires_review: bool` to `flows` (default false)
   - Add `last_validated_against_graph_version: int | None` to `flows`

7. **Add event types.** In `backend/app/modules/executions/event_types.py`:
   ```python
   FLOW_MARKED_STALE = "flow.marked_stale"
   FLOW_VALIDATED_AGAINST_NEW_GRAPH = "flow.validated_against_new_graph"
   FLOW_REQUIRES_REVIEW = "flow.requires_review"
   ```

8. **Render in the frontend.** In `frontend/components/flows/mission-row.tsx`, add badges:
   - "Stale" (orange) when `flow.stale_reason` is set
   - "Requires review" (red) when `flow.requires_review` is true
   
   In `frontend/components/flows/mission-detail-header.tsx`, show the staleness reason prominently with a "Review changes" affordance that opens a modal showing the assessment diff.

9. **Write tests in `test_test_maintainer.py`:**
    - `test_maintainer_marks_flow_stale_when_locator_missing`:
      ```python
      # Seed a flow with a "Sign In" button selector
      # Rediscover finds the button is now labeled "Log In"
      # Assert: assessment.is_still_valid == False, requires_review == True
      # Assert: flow.stale_reason mentions the locator change
      ```
    - `test_maintainer_confirms_valid_when_locators_intact`:
      ```python
      # Seed a flow; rediscover finds the same locators
      # Assert: assessment.is_still_valid == True, requires_review == False
      ```
    - `test_maintainer_never_modifies_success_condition`:
      ```python
      # Before: flow.success_condition = {"url_matches": "/dashboard"}
      # After maintainer runs
      # Assert: flow.success_condition is unchanged
      ```
    - `test_heuristic_fallback_when_ai_disabled`:
      ```python
      # AI_PROVIDER=none
      # Assert: maintainer returns a heuristic assessment with confidence=0.5
      ```
    - `test_proposed_locator_updates_not_auto_applied`:
      ```python
      # AI proposes new locators
      # Assert: flow.steps are unchanged — proposed_locator_updates are in the assessment, not the flow
      ```

---

## Acceptance criteria

- [ ] `TestMaintainer` class exists with `evaluate_stale_flow(flow_id)`.
- [ ] `AgentReasoner.evaluate_scenario_validity` exists with AI + heuristic fallback.
- [ ] `ScenarioValidityAssessment` schema exists with all 8 fields.
- [ ] `rediscover` calls the maintainer for every flow whose `last_validated_against_graph_version` is older than the current graph version.
- [ ] `POST /api/v1/projects/{id}/flows:evaluate-stale` endpoint exists.
- [ ] `Flow` model has `stale_reason`, `requires_review`, `last_validated_against_graph_version` columns.
- [ ] The maintainer NEVER modifies `flow.success_condition`. It only updates metadata fields.
- [ ] Frontend renders "Stale" and "Requires review" badges.
- [ ] All 5 new tests pass.

---

## Anti-patterns to avoid

- **Do NOT auto-rewrite the success_condition.** The brief is explicit: "An adaptive system must preserve the original acceptance criteria. Otherwise, it could silently change a test's meaning to accommodate a regression." Auto-rewriting criteria is the #1 way to silently turn a regression into a "pass."
- **Do NOT auto-apply proposed locator updates.** They are proposals — recorded in the assessment, never written to `flow.steps` without human sign-off.
- **Do NOT mark a flow as "still valid" with low confidence.** If the AI's confidence is < 0.7, default to `requires_review=true`. False confidence is worse than honest uncertainty.
- **Do NOT forget the heuristic fallback.** When AI is disabled, the maintainer still runs with the conservative "missing locators = requires review" heuristic.
- **Do NOT block `rediscover` on maintainer evaluation.** Re-crawl happens first; maintainer evaluation runs after and updates flows asynchronously. The user shouldn't wait for AI to re-evaluate 50 flows before the new graph is available.
- **Do NOT let the AI propose "lower the bar" criteria changes.** The system prompt explicitly forbids it; the schema has no field for "proposed_criteria_updates" (only `proposed_locator_updates`).
- **Do NOT remove the `requires_review` flag once set without explicit user action.** A flow that was once stale and required review stays in that state until a human reviews and clears it.

---

## Dependencies & references

- **Read first:** `backend/app/engine/exploration/discovery/pipeline.py` (`rediscover` method), `backend/app/modules/flows/service.py`, `backend/app/modules/flows/models.py`, `backend/app/engine/ai/reasoner.py` (existing methods for the pattern), `backend/app/modules/product_graph/service.py` (`get_current_version`).
- **Predecessor chunks:** `00-overview.md`, `01-productionize-agent-loop.md` (uses the agent infrastructure).
- **Brief reference:** §5 capability F (Test maintenance) + §4 Stage 8 (Regression and continuous validation).
