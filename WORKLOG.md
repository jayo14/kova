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
