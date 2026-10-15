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
