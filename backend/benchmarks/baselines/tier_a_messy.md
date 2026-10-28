# Kova Benchmark Report — 2026-10-28

**Suite:** tier-a-messy | **Agent Mode:** Deterministic (AI Off)

## Summary metrics
| Metric | Value | Target | Status |
|---|---|---|---|
| Scenario relevance | 0.00 | ≥0.80 | ❌ |
| True positive rate | 0.0% | ≥90% | ❌ |
| False positive rate | 100.0% | ≤5% | ❌ |
| Evidence quality | 100.0% | ≥98% | ✅ |
| Auth success rate | 0.0% | ≥95% | ❌ |
| Flow completion rate | 0.0% | ≥85% | ❌ |
| Evidence completeness | 100.0% | ≥98% | ✅ |
| Cost per validation | $0.0000 | ≤$0.05 | ✅ |
| Time per validation | 2.36s | ≤60s | ✅ |
| Model calls per validation | 0.0 | N/A | ℹ️ |
| Journeys found / labeled | 7 / 16 | Reported | ℹ️ |
| False journeys proposed | 7 | 0 desired | ℹ️ |
| Completion rate | 0.0% | Baseline −5 pp max regression | ℹ️ |
| Steps per journey | 0.00 | Reported | ℹ️ |
| False-pass rate | 0.0% | 0% | ✅ |
| False-fail rate | 100.0% | Reported | ℹ️ |
| UNVERIFIED rate | 100.0% | Reported | ℹ️ |
| Success without evidence | 0 | 0 | ✅ |

## Per-fixture results
| Fixture | Expected | Detected | FP | Completed | Auth | Evidence | Notes |
|---|---|---|---|---|---|---|---|
| messy_unlabeled_controls | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_unassociated_inputs | 1 | 0 | 0 | ❌ | N/A | 100% | Known defect input_labels_missing not detected or missing evidence |
| messy_blocking_overlays | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_spa_navigation | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_late_hydration | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_lazy_list | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_popups | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_native_dialogs | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_shadow_iframe | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_wizard | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_silent_failure | 1 | 0 | 0 | ❌ | N/A | 100% | Known defect save_not_persisted not detected or missing evidence |
| messy_toast_success | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_slow_flaky_api | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_marketing_only | 0 | 0 | 1 | ❌ | N/A | 100% | No defects reported |
| messy_authenticated_crud | 0 | 0 | 1 | ❌ | ❌ | 100% | No defects reported |
