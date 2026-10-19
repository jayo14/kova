# Chunk 09 — Product Graph provenance (Observed / Expected / Inferred)

> Phase: **B — Validation modes & project model**
> Predecessors: `00-overview.md`
> Successors: none
> Estimated time: 1.5 days

---

## Goal & context

The brief (§4 Stage 3 — Product understanding) is explicit:

> *"Kova should distinguish three things:*
> 1. *Observed facts: What the application actually exposes or does.*
> 2. *Expected behavior: What the user or specification says should happen.*
> 3. *Inferred behavior: What the AI believes should happen based on the available context.*
>
> *Keeping these categories separate is essential. Otherwise, the AI can mistake its own assumptions for the product's requirements."*

The audit found:
- `product_graph/schemas.py:33` has `source: Literal["user_provided", "discovered", "inferred", "ai_proposal"]` — but this conflates **where it came from** (process provenance) with **what kind of knowledge it is** (epistemic status).
- A `discovered` Page (observed fact) and a `discovered` Goal (which may be inferred from page observation) share the same `source` value — they're epistemically different.
- No first-class `business_rules`, `negative_scenarios`, `acceptance_criteria`, `unknowns` fields on Goal.
- `ProductModel` in `validation/models.py:26-43` is a separate flat schema with `purpose`, `capabilities`, `routes`, `roles`, `entities` — disconnected from the structured Product Graph, creating a dual-track schema that confuses consumers.

**This chunk adds `provenance: Literal["observed", "expected", "inferred", "user_provided"]`** to Page, Action, Capability, and Goal. It also adds first-class `business_rules`, `negative_scenarios`, `acceptance_criteria`, `unknowns` to Goal. And it deprecates the flat `ProductModel` in favor of the structured Product Graph.

This is Action 09 because the brief is explicit: "Otherwise, the AI can mistake its own assumptions for the product's requirements." Without provenance separation, Kova can't tell the difference between "the app definitely has a login page" (observed) and "the app probably requires authentication for the dashboard" (inferred).

---

## Files to touch

- `backend/app/modules/product_graph/schemas.py` — add `provenance` field; add Goal's new fields
- `backend/app/modules/product_graph/models.py` — add `provenance` column to all entity tables; add Goal's new JSON columns
- `backend/alembic/versions/0NN_add_provenance_to_product_graph.py` — migration
- `backend/app/modules/product_graph/repository.py` — query helpers by provenance
- `backend/app/modules/product_graph/service.py` — preserve provenance through `upsert_from_discovery` and `merge_user_edit`
- `backend/app/engine/exploration/discovery/pipeline.py` — tag discovered entities with `provenance="observed"`; tag inferred invariants with `provenance="inferred"`
- `backend/app/engine/ai/reasoner.py` — when `synthesize_journeys` infers a Goal from observation, tag `provenance="inferred"`
- `backend/app/modules/validation/models.py` — deprecate `ProductModel`; provide a migration path that reads from the structured Product Graph
- `backend/app/modules/validation/impact_analysis.py` — respect provenance: observed entities cannot be silently overwritten by inferred ones
- `backend/app/api/routes/projects.py` — `GET /api/v1/projects/{id}/product-graph` returns entities with provenance
- `frontend/components/projects/project-knowledge.tsx` — render provenance badges (Observed / Expected / Inferred / User-provided)
- `backend/tests/unit/test_product_graph_provenance.py` — new
- `backend/tests/integration/test_product_graph_db.py` — extend

---

## Step-by-step spec

1. **Define the provenance enum.** In `backend/app/modules/product_graph/schemas.py`:
   ```python
   class Provenance(str, Enum):
       OBSERVED = "observed"             # What the application actually exposes or does (from discovery)
       EXPECTED = "expected"             # What the user or specification says should happen
       INFERRED = "inferred"             # What the AI believes should happen based on context
       USER_PROVIDED = "user_provided"   # Explicitly provided by the user (overrides all)
   ```
   Note: this is distinct from the existing `source` field. `source` says "where this row came from" (discovery vs AI vs user). `provenance` says "what kind of knowledge this is" (observed fact vs expected behavior vs inferred hypothesis).

2. **Add `provenance` to every entity schema.** Extend `Page`, `Action`, `Capability`, `AuthCapability`, `Goal`, `State`, `Invariant`:
   ```python
   class Page(BaseModel):
       # ... existing ...
       provenance: Provenance = Provenance.OBSERVED
   ```
   Default `OBSERVED` for Page/Action/Capability (they come from discovery). Default `INFERRED` for Goal (it's an AI hypothesis). Default `EXPECTED` for user-supplied goals.

3. **Add Goal's new fields.** Extend `Goal`:
   ```python
   class Goal(BaseModel):
       # ... existing ...
       business_rules: list[str] = []                # invariants the app must maintain (e.g. "teachers cannot access other teachers' classes")
       negative_scenarios: list[str] = []             # things that should NOT happen (e.g. "student cannot enroll without paying")
       acceptance_criteria: list[StateAssertion] = [] # explicit pass conditions (separate from success_criteria, which is the executable form)
       unknowns: list[str] = []                        # things the AI isn't sure about and wants to investigate
   ```

4. **Add the ORM columns.** In `backend/app/modules/product_graph/models.py`, add `provenance: Mapped[str]` to every entity table (default `"observed"` for Page/Action/Capability, `"inferred"` for Goal). Add `business_rules`, `negative_scenarios`, `acceptance_criteria`, `unknowns` as JSON columns on `product_goals`.

5. **Write the migration.** `0NN_add_provenance_to_product_graph.py`:
   - Add `provenance` column to all 9 entity tables with appropriate defaults
   - Add the 4 new JSON columns to `product_goals`
   - Backfill: existing Page/Action/Capability rows get `"observed"`; existing Goal rows get `"inferred"` if `source == "ai_proposal"`, else `"user_provided"` if `source == "user_provided"`, else `"observed"` if `source == "discovered"`

6. **Preserve provenance through `upsert_from_discovery`.** In `backend/app/modules/product_graph/service.py`:
   ```python
   async def upsert_from_discovery(self, project_id, discovery_result):
       # Pages, Actions, Capabilities from discovery → provenance="observed"
       for page in discovery_result.pages:
           page.provenance = Provenance.OBSERVED
       # Goals inferred by AI → provenance="inferred"
       for goal in discovery_result.goals:
           if goal.source == "ai_proposal":
               goal.provenance = Provenance.INFERRED
           elif goal.source == "user_provided":
               goal.provenance = Provenance.EXPECTED
       
       # When merging: NEVER let an inferred entity overwrite an observed one
       # (preserve the higher-confidence provenance)
       ...
   ```

7. **Add provenance-aware queries.** In `backend/app/modules/product_graph/repository.py`:
   ```python
   async def get_capabilities_by_provenance(
       self, project_id: uuid.UUID, provenance: Provenance
   ) -> list[Capability]:
       """Return only capabilities with the given provenance."""
       stmt = select(ProductCapability).where(
           ProductCapability.project_id == project_id,
           ProductCapability.provenance == provenance.value,
       )
       res = await self.db.execute(stmt)
       return [self._row_to_capability(r) for r in res.scalars()]
   
   async def get_observed_facts(self, project_id: uuid.UUID) -> dict:
       """Return all entities with provenance='observed' — what the app actually has."""
       return {
           "pages": await self.get_pages_by_provenance(project_id, Provenance.OBSERVED),
           "actions": await self.get_actions_by_provenance(project_id, Provenance.OBSERVED),
           "capabilities": await self.get_capabilities_by_provenance(project_id, Provenance.OBSERVED),
       }
   
   async def get_inferred_hypotheses(self, project_id: uuid.UUID) -> dict:
       """Return all entities with provenance='inferred' — what the AI believes."""
       ...
   
   async def get_expected_behavior(self, project_id: uuid.UUID) -> dict:
       """Return all entities with provenance='expected' — what the user specified."""
       ...
   ```

8. **Respect provenance in impact analysis.** In `backend/app/modules/validation/impact_analysis.py`:
   ```python
   # When a flow's underlying capability has provenance="inferred",
   # the impact analysis should add an uncertainty:
   # "Flow X depends on capability Y, which is inferred (not observed).
   #  Run discovery to confirm the capability exists."
   ```

9. **Respect provenance in the AI reasoner.** When `synthesize_journeys` proposes a new Goal, tag it `provenance="inferred"`. When the user explicitly creates a Goal via the API, tag it `provenance="expected"`. Observed entities come only from discovery.

10. **Deprecate the flat `ProductModel` schema.** In `backend/app/modules/validation/models.py`, add a deprecation comment and a `to_structured_graph()` method that converts the flat schema to the structured Product Graph entities. New code should use the structured graph; old code that reads `ProductModel` should be migrated.

11. **Render provenance in the frontend.** In `frontend/components/projects/project-knowledge.tsx`, render badges:
    - Observed → blue dot with tooltip "Discovered from the application"
    - Expected → green dot with tooltip "Specified by the user"
    - Inferred → orange dot with tooltip "Inferred by AI — needs verification"
    - User-provided → purple dot with tooltip "Manually edited by the user"

12. **Add an "Observed vs Expected vs Inferred" filter to the Product Graph view.** Let the user toggle which provenance categories are visible. Default: all three.

13. **Write tests in `test_product_graph_provenance.py`:**
    - `test_discovered_page_has_observed_provenance`:
      ```python
      # Run discovery; assert Page.provenance == "observed"
      ```
    - `test_ai_inferred_goal_has_inferred_provenance`:
      ```python
      # AI proposes a Goal; assert Goal.provenance == "inferred"
      ```
    - `test_user_supplied_goal_has_expected_provenance`:
      ```python
      # User creates a Goal via the API; assert Goal.provenance == "expected"
      ```
    - `test_upsert_does_not_overwrite_observed_with_inferred`:
      ```python
      # Seed an observed Page
      # Run upsert_from_discovery with the same Page marked as inferred
      # Assert: Page.provenance is still "observed" (the higher-confidence value wins)
      ```
    - `test_goal_has_business_rules_negative_scenarios_unknowns_fields`:
      ```python
      goal = Goal(name="test", business_rules=["rule1"], negative_scenarios=["neg1"], unknowns=["?"])
      assert goal.business_rules == ["rule1"]
      ```
    - `test_get_observed_facts_returns_only_observed_entities`:
      ```python
      # Seed mixed-provenance entities
      facts = await repo.get_observed_facts(project_id)
      # Assert: only observed entities returned
      ```

---

## Acceptance criteria

- [ ] `Provenance` enum exists with all 4 values.
- [ ] Every Product Graph entity has a `provenance` field; migration applies cleanly; existing rows backfilled.
- [ ] `Goal` has `business_rules`, `negative_scenarios`, `acceptance_criteria`, `unknowns` fields.
- [ ] `upsert_from_discovery` preserves provenance — observed entities cannot be overwritten by inferred ones.
- [ ] Repository has `get_observed_facts`, `get_inferred_hypotheses`, `get_expected_behavior` helpers.
- [ ] `synthesize_journeys` tags AI-proposed Goals as `provenance="inferred"`.
- [ ] User-supplied Goals are tagged `provenance="expected"`.
- [ ] `ProductModel` (flat schema) is deprecated; new code uses the structured Product Graph.
- [ ] Frontend renders provenance badges and supports filtering.
- [ ] All 6 new tests pass.

---

## Anti-patterns to avoid

- **Do NOT conflate `source` and `provenance`.** They answer different questions: `source` = "where did this row come from?" (process), `provenance` = "what kind of knowledge is this?" (epistemic). Both fields coexist.
- **Do NOT let `inferred` entities silently overwrite `observed` ones.** If discovery finds a Page (observed) and the AI later infers the same Page should exist (inferred), the observed value wins. The inferred value is recorded as a hypothesis but doesn't replace the observed fact.
- **Do NOT let the AI mark its own inferences as `observed`.** The AI cannot observe — only the browser can. Inference is always `provenance="inferred"`.
- **Do NOT make `provenance` editable by the AI.** Only discovery (sets `observed`), the user (sets `expected` or `user_provided`), or the reasoner (sets `inferred`) can set provenance. The AI cannot change provenance of an existing entity.
- **Do NOT delete the flat `ProductModel` yet.** Deprecate it with a comment and a migration path; remove it in a future release. Existing consumers may break if you delete it abruptly.
- **Do NOT forget to backfill.** Every existing Product Graph row needs a `provenance` value. The migration must set sensible defaults based on the existing `source` field.
- **Do NOT make `unknowns` a list of strings without structure.** Each unknown should be a string that describes WHAT is unknown and WHY — e.g. "Whether the /admin route requires admin role — not yet tested".

---

## Dependencies & references

- **Read first:** `backend/app/modules/product_graph/schemas.py` (current schemas), `backend/app/modules/product_graph/models.py`, `backend/app/modules/product_graph/service.py` (`upsert_from_discovery`), `backend/app/modules/validation/models.py` (`ProductModel` flat schema), `backend/app/engine/exploration/discovery/pipeline.py`.
- **Predecessor chunks:** `00-overview.md`.
- **Brief reference:** §4 Stage 3 — Product understanding — "Keeping these categories separate is essential."
