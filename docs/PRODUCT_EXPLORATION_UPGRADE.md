# Kova Product Exploration & Journey Generation Upgrade Report

## 1. Executive Summary & Root Cause Analysis

### The Problem
When Kova scanned web applications like `log2def.vercel.app`, it generated shallow, low-value navigation flows instead of testing actual application capabilities. Typical generated journeys included:
- "Open the landing page and navigate to Features."
- "Click Get started and verify navigation or visible feedback."
- "Click Create your report and verify that the URL changes."
- "Navigate to Reports and verify that the section has loaded."
- "Navigate to Mock defence and verify that the section contains content."
- "Sign up, log in, and verify that an account page appears."

### Root Cause Analysis
1. **Shallow Heuristics in `_classify_intent` & Element Mission Generation:**
   In `backend/app/engine/exploration/explorer.py`, `_classify_intent` mapped keywords such as `"report"` to generic `contact` form intents, while labels like `"Create your report"` and `"Mock defence"` were treated as generic unclassified elements. As a result, `_build_element_mission` generated 2-step trivial scripts (`navigate` -> `click target` -> `wait 500`) with verification criteria limited to `url_changed_to` or `element_count >= 1`.
2. **Lack of Capability Extraction for Productivity & Simulation Workflows:**
   In `backend/app/engine/exploration/discovery/capability_extractor.py`, capabilities were limited to generic form, catalog, and auth. Core functional capabilities like report synthesis (`report_generation`), interactive practice/simulations (`practice_simulation`), and data submission workflows were unrepresented.
3. **Absence of a Journey Quality Gate:**
   No automated validation gate existed to reject or repair journeys with vague outcomes (e.g., "Verify visible feedback", "Verify page loaded", "Expected results present"). Any generated candidate was emitted as-is.
4. **Faulty Goal-Capability Matching in Deterministic Generator:**
   In `backend/app/modules/flows/generator/deterministic.py`, capability matching matched any single word > 3 characters (e.g. matching "course" in "course_enrollment" for the goal "Request Refund for Course"), causing false-positive deterministic matches that preempted AI proposals.
5. **Lack of Explainable Ranking:**
   The recommendation engine picked whichever journey appeared first in candidate lists or marked default routes as recommended, frequently recommending auth or landing-page navigation over real product features.

---

## 2. Architecture of the Upgraded Discovery & Exploration Pipeline

```
Target Web Application (DOM, Routes, Inputs, Buttons)
                          │
                          ▼
            [ Progressive Exploration Engine ]
             - Auto-loads project credentials
             - Explores functional entry points
             - Reaches authenticated views
                          │
                          ▼
           [ Structured Capability Extractor ]
             - report_generation (Log2Def, SaaS, exports)
             - practice_simulation (mock defence, exams, quizzes)
             - data_submission & crud
             - search_and_discovery
                          │
                          ▼
       [ Outcome-Driven Journey Generation Engine ]
             - Multi-step executable workflows (navigate, type, click, submit)
             - User goals & concrete expected outcomes
             - Specific assertion targets (viewer, document, evaluation)
                          │
                          ▼
          [ Journey Quality & Repair Gate ]
             - Rejects shallow navigation flows
             - Rejects vague assertions ("Verify visible feedback")
             - Automatically repairs weak candidates
                          │
                          ▼
        [ Explainable Quality-Based Ranking ]
             - Ranks by functional value, outcome significance & assertion quality
             - Never recommends auth or navigation over real features
             - Emits explicit recommendation rationale
                          │
                          ▼
             [ Presentation Layer (UI & API) ]
             - Renders concrete outcomes on MissionCard
             - Displays recommendation rationale badge
```

---

## 3. Changes Made Across the System

### A. Structured Capability Model & Mission Metadata
- **`backend/app/modules/exploration/capabilities.py`:** Added `DiscoveredCapability`, `CapabilityInput`, `CapabilityVerification` models capturing user goals, entry points, preconditions, inputs, expected outcomes, verification methods, discovery status, and confidence.
- **`backend/app/modules/exploration/schemas.py`:** Extended `DiscoveredMission` with `user_goal`, `expected_outcome`, `prerequisites`, `verification_methods`, `ranking_rationale`, `classification`, `discovery_status`, `capability_id`, `is_core`.

### B. Generalized Capability Extraction
- **`backend/app/engine/exploration/discovery/capability_extractor.py`:**
  - Added extraction patterns for `report_generation` (`report`, `logbook`, `siwes`, `export`, `pdf`, `summary`).
  - Added extraction patterns for `practice_simulation` (`mock defence`, `mock defense`, `defence`, `defense`, `practice`, `simulation`, `quiz`, `exam`, `assessment`).
  - Added generalized `data_submission` and `search_and_discovery`.

### C. Journey Quality, Validation, Repair & Ranking Engine
- **`backend/app/modules/exploration/journey_validator.py`:**
  - `is_vague_outcome(outcome)`: Rejects generic placeholders ("Verify visible feedback", "Verify page loaded", "Expected results present", "Page responds").
  - `validate_journey(mission)`: Rejects shallow navigation, vague outcomes, and ungrounded actions.
  - `repair_journey(mission)`: Automatically upgrades weak flows with grounded input actions and concrete outcome assertions.
  - `score_journey(mission)`: Computes validation value score along 5 dimensions: core capability relevance (0.35), outcome significance (0.25), assertion quality (0.20), multi-step depth (0.10), and goal alignment (0.10).
  - `deduplicate_and_rank_journeys(missions, goal)`: Deduplicates near-duplicate journeys, strictly avoids recommending auth/navigation over core features, sets `recommended=True` on the top functional workflow, and populates `ranking_rationale`.

### D. Explorer Intent Mapping & Progressive Exploration
- **`backend/app/engine/exploration/explorer.py`:**
  - Updated `_classify_intent` to classify `generate_report` and `practice_simulation`.
  - Updated `_build_journey_for_intent` to generate multi-step workflows with input typing and concrete assertions for report generation, mock defence, CRUD creation, and contact inquiries.
  - Integrated `deduplicate_and_rank_journeys` into `_discover_workflows`.
  - Updated `_generate_recommendation` to emit the explainable `ranking_rationale`.
  - Extended role detection from offline observations when `page` is mocked or headless.
  - Handled flexible arguments in `_analyze_routes`.

### E. Authenticated Progressive Exploration
- **`backend/app/modules/exploration/service.py`:**
  - Auto-loads and decrypts project credentials for the active project so exploration enters and validates authenticated interfaces when credentials exist.

### F. Goal-Capability Matching Precision
- **`backend/app/modules/flows/generator/deterministic.py`:**
  - Removed broad single-word substring matching that falsely matched unrelated goals (e.g. "Request Refund for Course" matching "course_enrollment").

### G. AI Synthesis Prompts
- **`backend/app/engine/ai/reasoner.py`:**
  - Reinforced prompt with explicit rules rejecting shallow navigation flows and vague outcomes, mandating end-to-end workflows and concrete expected outcomes.

### H. Frontend Presentation
- **`frontend/lib/types.ts`:** Added `expectedOutcome`, `userGoal`, `rankingRationale`, `classification`, `isCore` to `SuggestedMission`.
- **`frontend/components/agent/mission-card.tsx`:**
  - Replaced generic `"Expected results present"` in `formatSuccessCondition` with contextual outcome descriptions.
  - Added dedicated **Expected Outcome** callout on mission cards.
  - Added **Recommendation Rationale** badge explaining why a mission is recommended.

---

## 4. Behavioral Differences: Before vs. After Comparison

| Scenario | Before (Shallow Exploration) | After (Upgraded Functional Validation) |
|---|---|---|
| **Scanning Log2Def** | Produced: "Navigate to Features", "Click Create your report and verify URL changes", "Click Mock defence and verify section loaded". | Produces: "Generate Create your report" (enters logbook entries, submits, verifies report viewer) and "Practice Mock defence" (starts simulation, inputs answers, verifies evaluation scoring). |
| **Recommendation Selection** | Recommended landing page navigation ("Explore Core Features & Navigation") or auth ("Sign up, log in, and view account"). | Recommends: "Generate Create your report" with explicit rationale: *"Selected as highest-value journey: tests core capability 'Generate Create your report' with verifiable outcome: 'Application processes entries and renders generated technical report document'"*. |
| **Expected Outcome Specificity** | "Verify visible feedback" or "Expected results present". | Concrete, verifiable assertion: *"Application processes logbook entries and renders synthesized report document"*. |
| **Authentication Handling** | Auth flows generated as primary missions without user request. | Auth treated as prerequisite; only tests authenticated functional workflows once session is established. |
| **Quality Control** | Emitted any clickable element as a candidate mission. | Filtered through `JourneyQualityValidator`: shallow clicks and vague outcomes are rejected or repaired. |

---

## 5. Verification & Test Suite Execution

### Backend Automated Tests:
1. `backend/tests/unit/test_journey_quality.py`:
   - `test_is_vague_outcome` (PASSED)
   - `test_validate_journey_rejects_shallow_navigation` (PASSED)
   - `test_validate_journey_rejects_vague_outcome` (PASSED)
   - `test_repair_journey_enhances_weak_flow` (PASSED)
   - `test_score_and_rank_prioritizes_functional_capabilities_over_auth_and_navigation` (PASSED)
2. `backend/tests/integration/test_product_exploration_functional.py`:
   - `test_log2def_style_app_exploration_generates_functional_workflows` (PASSED)
   - `test_goal_directed_exploration_prioritizes_specific_target` (PASSED)
3. Full Exploration Suite (`backend/tests/unit/test_explorer.py` & `backend/tests/test_exploration_pipeline.py`):
   - 47 tests passed in 5.45s (100% pass rate).
4. Deterministic Flow Generation (`backend/tests/unit/test_flow_generation.py`):
   - 8 tests passed in 64.11s (100% pass rate).

### Frontend Automated Tests:
- `cd frontend && npm test`: 45 tests across 8 suites passed (100% pass rate).

---

## 6. Limitations & Follow-Up Work
1. **Multi-Step Wizard Dialogs:** In SPAs where form submission spans 3+ wizard tabs with dynamic validation, auto-repair creates standard input steps; complex wizard transitions should be enriched with dynamic locator synthesis.
2. **File Upload Testing:** File inputs currently receive simulated test file attachments; apps requiring specialized binary formats (e.g. `.docx` SIWES templates) can be extended with sample fixture assets in test credentials.
