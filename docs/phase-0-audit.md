# Phase 0 Audit: Demo, Mock, and Stub Surfaces

Date: 2026-10-15  
Status: Complete  
Author: Kova Engineering Team  

## Overview
As part of Kova's production readiness roadmap (Phase 0: Clean Break), a codebase-wide audit was conducted to identify, eliminate, gate, or justify all demo, mock, stub, and placeholder surfaces across the frontend and backend.

Kova operates on the principle that the execution engine is deterministic and reality-grounded. Screenshots, verifications, flow executions, and metrics must correspond to real observable state in a real browser session.

---

## Audit Findings & Decisions

| Surface / File | Identification | Decision | Rationale |
|---|---|---|---|
| `backend/app/engine/exploration/explorer.py` (`fake_route`) | Heuristic route generator variable named `fake_route` for URL-pattern guesses | Renamed & calibrated | Renamed to `inferred_route` with `confidence: 0.0` and `source: "heuristic"`. Heuristic suggestions are explicitly flagged and never disguised as observed navigation facts. |
| `backend/scripts/diagnose_agent.py` | Standalone CLI agent diagnostic script containing simulated/sample data | Gated | Gated behind `settings.DEBUG`. Gated CLI tool with explicit exit error if `settings.DEBUG` is false. |
| `backend/scripts/diagnose_ai_providers.py` | Standalone CLI diagnostic script for testing LLM providers with sample inputs | Gated | Gated behind `settings.DEBUG`. Prevents unintended execution in production environments while keeping developer ergonomics. |
| `backend/app/api/routes/ci.py` (`POST /api/v1/ci/run`) | CI execution dispatch endpoint | Audited / Leave | Confirmed always dispatches real Celery/background execution tasks with browser drivers. No dry-run or mock pass shortcut exists. |
| `backend/app/modules/executions/evidence_model.py` | `Evidence` ORM model lacked purpose and step attribution | Schema migration applied | Added `purpose` (e.g. `step_evidence`, `verification`, `diff`, `failure`) and `step_id` columns with foreign key relationship. Migration `014_add_evidence_purpose.py` backfills legacy rows with `purpose="legacy"`. |
| `backend/app/modules/executions/evidence_service.py` | `EvidenceService.create` and `capture_screenshot` previously allowed unassigned orphan evidence | Enforced strict validation | Both methods now strictly enforce non-null `purpose` and require either `step_id` or explicit purpose. Rejects unattached orphan rows with `ValueError`. |
| `backend/app/engine/browser/screenshot_storage.py` & `evidence_storage.py` | Evidence capture routines did not propagate step/purpose metadata | Updated | Updated signatures to accept and propagate `purpose` and `step_id` to `EvidenceService`. |
| `backend/app/engine/execution/runner.py` | Screenshot captures during flow execution | Updated | Every call to `screenshot_storage.capture()` passes explicit `purpose="step_evidence"` and the active `step_id`. |
| `backend/app/engine/verification/verifier.py` | Verification results checking state without linking evidence | Updated | Verification routines now capture screenshots with `purpose="verification"` and associate resulting `evidence_ids` directly in the verification result payload. |
| `frontend/components/executions/evidence-viewer.tsx` & `screenshot-gallery.tsx` | Flat list rendering of screenshots with potential unlinked images | Updated | Grouped display by `step_id` and `purpose`. Orphan screenshots missing `step_id` and `purpose` are suppressed in production and trigger a developer warning banner in development mode. |
| `examples/buggy-demo/` | Multi-page mock web app fixture | Preserved (Leave) | Legitimate local fixture repository used for regression testing Kova's crawler, verifier, and healing engine. |
| `backend/tests/**` | Unit and integration test mocks (`unittest.mock`, `AsyncMock`) | Preserved (Leave) | Legitimate test suite isolation mocks. No production code path uses these. |
| Marketing / landing page mock illustrations | Visual UI previews in landing pages | Preserved (Leave) | Marketing assets and illustrations; separated from application execution flows. |

---

## Verification & Integrity Guarantees

1. **Grep Cleanliness**:
   - `rg -n "demo_mode|mock_mode|use_dummy|placeholder_|fake_|stub_"` produces 0 hits in active production paths (excluding tests, examples, and node modules).
2. **Database Integrity**:
   - Migration `014_add_evidence_purpose.py` applies cleanly and ensures all `Evidence` rows have a non-null `purpose`.
3. **Automated Regression Suite**:
   - `backend/tests/integration/test_evidence_integrity.py` validates that:
     - Attempts to create orphan evidence without `purpose` or `step_id` raise `ValueError`.
     - Evidence roundtrips persist `purpose` and `step_id` reliably.
