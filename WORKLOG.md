# Kova Production Readiness Worklog

## Chunk 01 — Eradicate hardcoded heuristics in ChangeImpactAnalyzer
- **Status:** Done
- **Changes:**
  - Removed all hardcoded capability string literals (`"course_enrollment"`, `"checkout"`, `"profile_management"`, `"authentication"`) from `ChangeImpactAnalyzer`.
  - Replaced heuristic matching with deterministic Product Graph lookup against stored capabilities (`source_files`, `routes`, and `kind == "shared"`).
  - Extended `ImpactReport` schema with `product_graph_consulted: bool`, `unmatched_files: list[str]`, and `uncertainties` property.
  - Extended `DiscoveredCapability` schema with `source_files: list[str]` and `kind: str`.
  - Added `get_product_model` to `ProjectRepository` and `ValidationService`.
  - Updated `analyze_impact` in `ValidationService` to pass the stored Product Graph capabilities or an empty dict.
  - If Product Graph is empty or has no capabilities and files are changed, `ChangeImpactAnalyzer` honestly reports `recommended_scope="full"`, `confidence=0.0`, and `"No Product Graph available; cannot perform targeted validation. Run Product Discovery first."`.
  - Updated `backend/tests/unit/test_continuous_validation.py` and `backend/tests/integration/test_resolver.py` with seeded Product Graph fixtures, unmatched file handling, and empty graph regression tests.
- **Tests Passing:**
  - `pytest backend/tests/unit/test_continuous_validation.py backend/tests/integration/test_resolver.py -v` (29 passed)

## Chunk 02 — Replace hardcoded auth URL patterns with semantic multi-signal discovery
- **Status:** Done
- **Changes:**
  - Created `AuthSignalBundle` and `AuthPageClassification` schemas supporting deterministic signal scoring across DOM inputs, action attributes, form types, text heuristics, and URL cues with confidence scoring and fallback to `ambiguous` or `AgentReasoner.classify_auth_page()`.
  - Added Levenshtein fuzzy matching and accessibility role/aria discovery in `find_submit_button`.
  - Integrated `observe_auth_signals` into `PageObserver` and `Explorer`, firing `"auth_classified"` events.
  - Added unit test suite `test_semantic_auth_discovery.py` and SPA Keycloak integration test in `test_agent_robustness.py`.
- **Tests Passing:**
  - `pytest backend/tests/unit/test_semantic_auth_discovery.py` (9 passed)
  - `pytest backend/tests/integration/test_agent_robustness.py -k test_non_standard_spa_keycloak_auth_classification` (1 passed)

## Chunk 03 — Real dependency resolver with State/Capability/Prerequisite semantics
- **Status:** Done
- **Changes:**
  - Added schemas in `backend/app/modules/flows/schemas.py`: `StateAssertion`, `State`, `StateMutation`, `Prerequisite`, `Capability`, `FlowStateContract`, and `ResetStrategy`.
  - Extended `FlowCreate`, `FlowUpdate`, and `FlowRead` with `state_contract` plus convenience properties `requires_state`, `produces_state`, `mutates_state`, `cost`.
  - Added `state_contract` column to `Flow` ORM model in `backend/app/modules/flows/models.py`.
  - Added Alembic migration `backend/alembic/versions/013_add_state_contract_to_flows.py`.
  - Updated `FlowRepository` in `backend/app/modules/flows/repository.py` to support `state_contract` on `create` and `update`.
  - Rewrote `backend/app/modules/flows/dependency_resolver.py` implementing `resolve_execution_plan` with state matching, capability provider ranking (cost, persona, credentials), cycle detection (state-key and flow-id graphs), fail-closed handling of unresolved states, state contamination detection, and reset strategy execution (`teardown` step insertion, `skip_if_exists`, `re_establish`).
  - Preserved backward-compatible shim `resolve_dependency_plan` returning `PlannedFlow` dicts for legacy callers.
  - Added unit test suite in `backend/tests/unit/test_flow_dependencies.py` for linear, reusable capability, state contamination, unsatisfiable, cycle, and cost/current_state skip plans.
  - Added `test_flow_state_contract_roundtrip` to `backend/tests/integration/test_flow_db.py`.
- **Tests Passing:**
  - `pytest backend/tests/unit/test_flow_dependencies.py backend/tests/integration/test_flow_db.py -v` (17 passed)
  - `pytest backend/tests/unit/test_continuous_validation.py backend/tests/integration/test_resolver.py -v` (29 passed)

## Chunk 04 — Eliminate demo/mock/stub data and enforce evidence purpose
- **Status:** Done
- **Changes:**
  - Added `purpose` and `step_id` columns to `Evidence` model in `backend/app/modules/executions/evidence_model.py`.
  - Added migration `014_add_evidence_purpose.py` backfilling existing evidence rows with `purpose="legacy"`.
  - Updated `EvidenceRead` schema in `backend/app/modules/executions/evidence_schemas.py`.
  - Updated `EvidenceRepository` and `EvidenceService` to strictly enforce `purpose` and `step_id`, rejecting unattached orphan rows with `ValueError`.
  - Updated browser `screenshot_storage.py` and `evidence_storage.py` to accept and propagate `purpose` and `step_id`.
  - Updated execution `runner.py` to pass `purpose="step_evidence"` and active `step_id` for every screenshot.
  - Updated `verifier.py` to capture screenshots with `purpose="verification"` and link `evidence_ids` in verification results.
  - Updated frontend evidence viewer and screenshot gallery components to group screenshots by `step_id` and `purpose`, suppressing orphans and showing dev warnings.
  - Renamed `fake_route` to `inferred_route` in explorer.py with `confidence: 0.0` and `source: "heuristic"`.
  - Gated CLI diagnostic scripts (`diagnose_agent.py`, `diagnose_ai_providers.py`) behind `settings.DEBUG`.
  - Created `docs/phase-0-audit.md` documenting decisions across all demo/mock/stub surfaces.
  - Created `backend/tests/integration/test_evidence_integrity.py` and updated `backend/tests/test_evidence.py`.
- **Tests Passing:**
  - `pytest backend/tests/test_evidence.py backend/tests/integration/test_evidence_integrity.py -v` (13 passed)
  - Full suite regression passes.

## Chunk 05 — Build the Product Graph data model
- **Status:** Done
- **Changes:**
  - Created `backend/app/modules/product_graph/schemas.py` with typed Pydantic models for all nine entities: `Goal`, `Persona`, `Page`, `Action`, `Capability`, `State`, `FlowGraphNode`, `Dependency`, `Invariant`, along with `ProductGraphExport`, `GraphDiff`, and `DiscoveryResult`. Normalized `url_pattern` on `Page` and aligned `Flow.state_contract` with Chunk 03 schemas.
  - Created `backend/app/modules/product_graph/models.py` with SQLAlchemy ORM tables: `product_goals`, `product_personas`, `product_pages`, `product_actions`, `product_capabilities`, `product_states`, `product_dependencies`, `product_invariants`, and `product_graph_versions`.
  - Added `product_graph_version` and `product_graph_updated_at` to `Project` model in `backend/app/modules/projects/models.py`.
  - Added `goal_id`, `persona_id`, and `page_ids` to `Flow` ORM model, `FlowCreate`, `FlowUpdate`, and `FlowRead` schemas, and repository/service methods.
  - Created migration `backend/alembic/versions/015_product_graph_tables.py` creating the nine tables, version tracking, flow/project extensions, and migrating existing `product_models` data into `product_capabilities`, `product_pages`, and `product_personas`.
  - Created `ProductGraphRepository` in `backend/app/modules/product_graph/repository.py` providing CRUD for all entities and five graph-traversal helpers: `flows_producing_capability`, `flows_requiring_state`, `pages_touched_by_flow`, `capabilities_produced_by_flow`, `invariants_checked_by_flow`.
  - Created `ProductGraphService` in `backend/app/modules/product_graph/service.py` implementing `export`, `diff`, `upsert_from_discovery` (preserving user-edited entities), and `merge_user_edit` with automated version bumping and snapshotting.
  - Added API endpoints in `backend/app/api/routes/projects.py`:
    - `GET /api/v1/projects/{project_id}/product-graph` (200 for owner, 403 for non-member, 404 if missing)
    - `PUT /api/v1/projects/{project_id}/product-graph` (allows user edit patches or discovery merges)
    - `GET /api/v1/projects/{project_id}/product-graph/diff?from=v1&to=v2`
  - Created unit tests `backend/tests/unit/test_product_graph_schemas.py` and integration tests `backend/tests/integration/test_product_graph_db.py`.
- **Tests Passing:**
  - `pytest backend/tests/integration/test_flow_db.py backend/tests/integration/test_project_db.py backend/tests/unit/test_continuous_validation.py backend/tests/unit/test_flow_dependencies.py -v` (33 passed)

## Chunk 06 — Modular multi-stage product discovery pipeline
- **Status:** Done
- **Changes:**
  - Refactored monolithic exploration engine into modular multi-stage `DiscoveryPipeline` subpackage under `backend/app/engine/exploration/discovery/`:
    - `crawler.py`: BFS crawler with path parameterization (`/courses/101` -> `/courses/:id`), budget controls (`max_depth`, `max_pages`), and SSRF protection (`_is_safe_url`).
    - `auth_detector.py`: Auth boundary mapping leveraging Chunk 02's `observe_auth_signals` and `classify_auth_page`.
    - `persona_detector.py`: Multi-role persona detection from role switchers, dropdowns, and route prefixes.
    - `capability_extractor.py`: Interactive action extraction (buttons, forms, links) with DOM selectors and heuristic/state mutation grouping.
    - `invariant_inferrer.py`: Deterministic invariant generation for auth boundaries, state mutations, and destructive actions.
    - `ai_assistant.py`: Bounded AI pattern assistance for ambiguous UI patterns, with confidence capped at `<= 0.9` and `source="ai_assistant"`.
    - `pipeline.py`: Pipeline orchestrator supporting full discovery and incremental rediscovery (`rediscover()`).
  - Added discovery settings `DISCOVERY_MAX_DEPTH` (default 3, max 5) and `DISCOVERY_MAX_PAGES` (default 50, max 200) to `backend/app/config/settings.py`.
  - Added `confidence` and `source` attribution across entity schemas and `AIProposal` in `backend/app/modules/product_graph/schemas.py`.
  - Integrated `DiscoveryPipeline` into `ExplorationEngine` and `ExplorationService`, firing `product_graph.updated` WebSocket events upon discovery completion.
  - Updated `ProductGraphService.upsert_from_discovery` to preserve discovered entity IDs and map page IDs to prevent foreign key constraint violations.
  - Added unit test suite `backend/tests/unit/test_discovery_pipeline.py` and end-to-end integration test `backend/tests/e2e/test_exploration_flow.py::test_discovery_pipeline_to_product_graph_e2e`.
- **Tests Passing:**
  - `pytest backend/tests/unit/test_explorer.py backend/tests/unit/test_discovery_pipeline.py backend/tests/e2e/test_exploration_flow.py -v` (26 passed)

## Chunk 07 — Flow Generation (Product Graph → executable flows)
- **Status:** Done
- **Changes:**
  - Created modular flow generation subpackage `backend/app/modules/flows/generator/`:
    - `schemas.py`: Defined `ExecutionStep`, `GeneratedFlow`, `GenerationRequest`, and `GenerationResult`.
    - `representations/internal.py`: Built internal execution plan steps (`step_navigate`, `step_locate`, `step_input`, `step_click`, `step_assert`, `step_capture_evidence`, `to_runner_steps`).
    - `representations/json_repr.py`: Serialized flows to diff-able JSON dicts and built `diff_flows` semantic comparator.
    - `representations/gherkin.py`: Generated human-readable Gherkin feature exports (`Feature:`, `Scenario:`, `Given`, `When`, `Then`).
    - `deterministic.py`: Deterministically walked the Product Graph (capabilities, pages, actions, personas, goals) without AI or hardcoded selectors.
    - `ai_proposer.py`: Integrated bounded fallback AI proposals for unresolved goals via `AgentReasoner.propose_flows()`, capping confidence at `<= 0.9` with `source="ai_proposal"` and audit records in `ai_proposals`.
  - Added additive columns `source`, `confidence`, `active` (default False for generated flows, requiring human review before CI eligibility), `json_repr`, and `gherkin_repr` to `Flow` ORM model, Alembic migration `016_add_generated_flow_columns.py`, `FlowCreate`, `FlowUpdate`, `FlowRead`, and `FlowRepository`.
  - Implemented `FlowService.generate_flows()` to orchestrate deterministic generation, conditional AI fallback, and persistence as inactive flows.
  - Added API route `POST /api/v1/projects/{project_id}/flows:generate` returning 200 for project owner/admin, 403 for non-members, and 404 for missing projects.
  - Added unit test suite `backend/tests/unit/test_flow_generation.py` and integration tests in `backend/tests/integration/test_flow_db.py`.
- **Tests Passing:**
  - `pytest backend/tests/unit/test_flow_generation.py backend/tests/integration/test_flow_db.py -v` (16 passed)
  - `pytest backend/tests/unit/test_flow_generation.py backend/tests/integration/test_flow_db.py backend/tests/unit/test_product_graph_schemas.py backend/tests/integration/test_product_graph_db.py backend/tests/unit/test_flow_dependencies.py backend/tests/unit/test_discovery_pipeline.py backend/tests/unit/test_explorer.py -v` (61 passed)


