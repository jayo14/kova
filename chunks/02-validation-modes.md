# Chunk 02 — Five validation modes as first-class concepts

> Phase: **B — Validation modes & project model**
> Predecessors: `00-overview.md`
> Successors: `10-visual-validation-mode.md` (implements the visual mode this chunk declares)
> Estimated time: 1.5 days

---

## Goal & context

The brief (§9) defines **5 validation modes** as complementary forms of validation that share execution, evidence, and reporting infrastructure but differ in scenario selection, assertion type, and result interpretation:

> *"Functional validation: Does a feature perform its intended operation?*
> *Workflow validation: Can a user complete an end-to-end journey with the required state transitions and dependencies?*
> *Regression validation: Does previously verified behavior still work after a change?*
> *Exploratory validation: Can Kova discover meaningful unexpected behaviors or missing cases beyond a predetermined list?*
> *Visual validation: Does the rendered interface match the applicable visual expectations, and are there relevant layout or presentation defects?"*

Today Kova has only one first-class concept: `ValidationScope = {targeted, expanded, full}` (`backend/app/modules/validation/models.py:11-14`) — which is a *scope*, not a *mode*. The audit found:

- `functional` — ❌ absent
- `workflow` — ⚠️ only a `category` literal on `AIGeneratedJourney` (`engine/ai/schemas.py:175`)
- `regression` — ✅ the only properly-implemented mode (via `RegressionFlowSelector`)
- `exploratory` — ⚠️ implicit in `ExplorationEngine`, not unified with regression
- `visual` — ❌ entirely absent (`observer.py:3, 19` says "no visual AI")

**This chunk adds `ValidationMode` as a first-class enum on `Flow` and `Execution`**, wires distinct success criteria per mode, and adds an `ExploratoryRunner` distinct from `RegressionRunner`. Visual validation is declared here but its implementation is deferred to action 10.

This is Action 02 because the brief explicitly calls these out as "complementary forms of validation" that "share the same underlying execution, evidence, and reporting infrastructure. They differ in how scenarios are selected, what constitutes an assertion, and how results are interpreted." Without first-class modes, Kova cannot distinguish "did this feature work" from "did this regression slip through" from "did the visual layout break."

---

## Files to touch

- `backend/app/modules/validation/models.py` — add `ValidationMode` enum
- `backend/app/modules/flows/schemas.py` — add `mode: ValidationMode` to `FlowCreate`/`FlowRead`/`FlowUpdate`
- `backend/app/modules/flows/models.py` — add `mode` column to `Flow` ORM
- `backend/app/modules/executions/schemas.py` — add `mode` to `ExecutionRead` (inherited from the flow)
- `backend/app/modules/executions/models.py` — add `mode` column to `Execution` ORM
- `backend/alembic/versions/0NN_add_validation_mode.py` — migration
- `backend/app/modules/validation/runner.py` — branch execution by mode
- `backend/app/modules/validation/exploratory_runner.py` — NEW; distinct runner for exploratory mode
- `backend/app/modules/validation/regression_runner.py` — refactor existing runner.py into this for clarity
- `backend/app/modules/validation/functional_runner.py` — NEW; thin wrapper for single-feature validation
- `backend/app/modules/validation/workflow_runner.py` — NEW; thin wrapper for end-to-end journeys
- `backend/app/modules/validation/visual_runner.py` — NEW stub; real impl in action 10
- `backend/app/modules/validation/success_criteria.py` — NEW; per-mode success criteria definitions
- `backend/tests/unit/test_validation_modes.py` — new
- `frontend/components/flows/mission-detail-header.tsx` — render mode badge
- `frontend/components/executions/execution-header.tsx` — render mode badge

---

## Step-by-step spec

1. **Define the enum.** In `backend/app/modules/validation/models.py`:
   ```python
   class ValidationMode(str, Enum):
       FUNCTIONAL = "functional"        # Does a feature perform its intended operation?
       WORKFLOW = "workflow"             # Can a user complete an end-to-end journey?
       REGRESSION = "regression"         # Does previously verified behavior still work?
       EXPLORATORY = "exploratory"       # Can Kova discover unexpected behaviors?
       VISUAL = "visual"                 # Does the rendered interface match expectations?
   ```
   Document each mode with a one-line description matching the brief.

2. **Add `mode` to the Flow schema + ORM.** In `backend/app/modules/flows/schemas.py`:
   ```python
   class FlowCreate(BaseModel):
       # ... existing ...
       mode: ValidationMode = ValidationMode.FUNCTIONAL
   ```
   In `backend/app/modules/flows/models.py`, add a `mode: Mapped[str]` column with default `"functional"`. Add to `FlowRead`, `FlowUpdate`.

3. **Add `mode` to the Execution schema + ORM.** Inherited from the flow at execution-creation time. Add column; backfill existing executions with `"regression"` (the closest match to current behavior).

4. **Write the migration.** `0NN_add_validation_mode.py`:
   - Add `mode` column to `flows` and `executions` tables
   - Backfill: existing flows get `"regression"` if they have `goal_id` set, else `"functional"`
   - Existing executions get the same as their parent flow

5. **Define per-mode success criteria.** In `backend/app/modules/validation/success_criteria.py`:
   ```python
   class SuccessCriteria(BaseModel):
       mode: ValidationMode
       required_assertions: list[str]          # which assertion types must pass
       optional_assertions: list[str]          # which contribute evidence but not pass/fail
       failure_tolerance: Literal["zero", "bounded", "investigative"]
       # zero: any failure = mode failure (functional, workflow, regression)
       # bounded: up to N failures acceptable (exploratory — discoveries are good)
       # investigative: failures are the point (visual when looking for defects)
       evidence_required: list[Literal["screenshot", "network_log", "dom_snapshot", "video", "trace"]]
       max_duration_seconds: int
       max_turns: int                          # for agent-loop runs
   
   FUNCTIONAL_CRITERIA = SuccessCriteria(
       mode=ValidationMode.FUNCTIONAL,
       required_assertions=["state_transition", "postcondition"],
       optional_assertions=["network_success"],
       failure_tolerance="zero",
       evidence_required=["screenshot", "network_log"],
       max_duration_seconds=300,
       max_turns=30,
   )
   WORKFLOW_CRITERIA = SuccessCriteria(
       mode=ValidationMode.WORKFLOW,
       required_assertions=["state_transition", "postcondition", "downstream_effect"],
       optional_assertions=["network_success", "persistence_after_reload"],
       failure_tolerance="zero",
       evidence_required=["screenshot", "network_log", "dom_snapshot"],
       max_duration_seconds=600,
       max_turns=60,
   )
   REGRESSION_CRITERIA = SuccessCriteria(
       mode=ValidationMode.REGRESSION,
       required_assertions=["baseline_match"],  # compared against last-known-good
       optional_assertions=[],
       failure_tolerance="zero",
       evidence_required=["screenshot"],
       max_duration_seconds=300,
       max_turns=30,
   )
   EXPLORATORY_CRITERIA = SuccessCriteria(
       mode=ValidationMode.EXPLORATORY,
       required_assertions=[],  # exploration has no required pass
       optional_assertions=["unexpected_behavior_detected", "defect_discovered"],
       failure_tolerance="investigative",  # discoveries are good
       evidence_required=["screenshot", "network_log", "dom_snapshot", "video"],
       max_duration_seconds=900,
       max_turns=80,  # allow more turns for investigation
   )
   VISUAL_CRITERIA = SuccessCriteria(
       mode=ValidationMode.VISUAL,
       required_assertions=["visual_reference_match"],  # impl in action 10
       optional_assertions=["layout_no_overflow", "color_contrast_ok"],
       failure_tolerance="zero",
       evidence_required=["screenshot"],
       max_duration_seconds=180,
       max_turns=15,
   )
   ```

6. **Refactor the validation runner.** In `backend/app/modules/validation/runner.py` (currently `ValidationRunner`), branch by mode:
   ```python
   class ValidationRunner:
       async def run(self, request, plan):
           mode = request.mode or plan.target_flow.mode or ValidationMode.FUNCTIONAL
           criteria = SUCCESS_CRITERIA[mode]
           
           if mode == ValidationMode.REGRESSION:
               return await RegressionRunner(criteria).run(request, plan)
           elif mode == ValidationMode.EXPLORATORY:
               return await ExploratoryRunner(criteria).run(request, plan)
           elif mode == ValidationMode.WORKFLOW:
               return await WorkflowRunner(criteria).run(request, plan)
           elif mode == ValidationMode.VISUAL:
               return await VisualRunner(criteria).run(request, plan)
           else:  # FUNCTIONAL
               return await FunctionalRunner(criteria).run(request, plan)
   ```

7. **Implement `ExploratoryRunner`.** Distinct from `RegressionRunner`:
   - Does NOT compare against a baseline (regression does)
   - Uses the agent loop (action 01) with `objective="discover unexpected behaviors in <feature>"`
   - Increases `max_turns` per `EXPLORATORY_CRITERIA`
   - Counts any discovered defect as a SUCCESS for the exploratory run (the goal is to find things, not to pass)
   - Emits `defect_discovered` events when the agent reports unexpected behavior

8. **Implement `FunctionalRunner`.** Thin wrapper:
   - Runs the deterministic flow (single feature)
   - Asserts the feature's `produces_state` mutation occurred
   - Catches network errors as failures (per `FAIL_ON_NETWORK_ERRORS`)

9. **Implement `WorkflowRunner`.** Distinct from `FunctionalRunner`:
   - Runs a multi-step journey with prerequisite resolution (chunk 03 of launch pack)
   - Asserts the journey's `success_condition` AND downstream effects (e.g. "course appears in dashboard after enrollment")
   - Checks `persistence_after_reload` (navigate away, navigate back, verify state still there)

10. **Implement `VisualRunner` as a stub.** Real implementation comes in action 10. For now:
    ```python
    class VisualRunner:
        async def run(self, request, plan):
            return ValidationReport(
                overall_status="unverified",
                failure_reason="Visual validation not yet implemented. See action 10.",
            )
    ```

11. **Update `POST /api/v1/ci/validate` to accept `mode`.** The existing endpoint accepts a diff and runs the planner. Extend the request schema to optionally include `mode: ValidationMode`. When omitted, infer from the diff context (regression by default for CI runs).

12. **Render mode badges in the frontend.** In `frontend/components/flows/mission-detail-header.tsx` and `frontend/components/executions/execution-header.tsx`, add a badge showing the flow/execution's mode. Use distinct colors per mode:
    - functional → blue
    - workflow → purple
    - regression → gray
    - exploratory → orange
    - visual → pink

13. **Write tests in `test_validation_modes.py`:**
    - `test_each_mode_has_success_criteria` — assert all 5 modes are in `SUCCESS_CRITERIA`
    - `test_functional_runner_fails_on_network_error` — mock a 500 response, assert overall_status == "failed"
    - `test_workflow_runner_checks_persistence_after_reload` — mock navigation, assert the runner reloads the page and re-checks state
    - `test_regression_runner_compares_baseline` — seed a baseline screenshot, run regression, assert overall_status == "passed" if no diff, "failed" if diff
    - `test_exploratory_runner_counts_defect_as_success` — agent discovers a defect, assert overall_status == "passed" with `discoveries: 1`
    - `test_visual_runner_stub_returns_unverified` — assert the stub returns "unverified" with the action-10 message

---

## Acceptance criteria

- [ ] `ValidationMode` enum exists with all 5 values.
- [ ] `Flow.mode` and `Execution.mode` columns exist; migration applies cleanly; existing rows backfilled.
- [ ] `SUCCESS_CRITERIA` dict exists with all 5 modes' criteria.
- [ ] `ValidationRunner` branches by mode and dispatches to the appropriate sub-runner.
- [ ] `FunctionalRunner`, `WorkflowRunner`, `RegressionRunner`, `ExploratoryRunner` are implemented and distinct.
- [ ] `VisualRunner` exists as a stub returning "unverified" with the action-10 message.
- [ ] `POST /api/v1/ci/validate` accepts `mode` in the request body.
- [ ] Frontend renders mode badges with distinct colors.
- [ ] All 6 new tests pass.

---

## Anti-patterns to avoid

- **Do NOT make modes mutually exclusive at the project level.** A project should be able to run functional, workflow, regression, exploratory, and visual validations against the same app. Modes are per-flow, not per-project.
- **Do NOT auto-infer mode from goal text.** The user must explicitly choose. If they don't, default to `functional` (single-feature check).
- **Do NOT make exploratory mode a "free for all".** It still has `max_turns=80` and `max_duration_seconds=900`. Exploration without limits becomes expensive and unsafe (per the brief §6: "Autonomy without limits can become expensive, slow, or unsafe.").
- **Do NOT let visual mode share `success_condition` with functional mode.** Visual validation needs a `visual_reference` artifact (screenshot + a11y tree) — action 10 implements this. The stub returns "unverified" until then.
- **Do NOT break the existing CI flow.** `POST /api/v1/ci/validate` without a `mode` field defaults to `regression` (current behavior). Backward compatible.
- **Do NOT remove `ValidationScope`.** It's still useful as a sub-property of regression mode (targeted / expanded / full). The two enums are orthogonal: `mode` says WHAT kind of validation; `scope` says HOW BROAD the regression is.

---

## Dependencies & references

- **Read first:** `backend/app/modules/validation/models.py` (current `ValidationScope`), `backend/app/modules/validation/runner.py` (current `ValidationRunner`), `backend/app/modules/validation/selector.py` (`RegressionFlowSelector`), `backend/app/modules/flows/schemas.py` (Flow schema), `backend/app/modules/executions/models.py` (Execution).
- **Predecessor chunks:** `00-overview.md`.
- **Successor chunks:** `10-visual-validation-mode.md` (implements the visual mode this chunk declares as a stub).
- **Brief reference:** §9 "Validation modes".
