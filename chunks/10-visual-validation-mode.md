# Chunk 10 — Visual validation mode (screenshot-diff + VLM)

> Phase: **C — AI capabilities E, F, H + visual**
> Predecessors: `00-overview.md`, `02-five-validation-modes.md` (declared visual as a stub)
> Successors: none
> Estimated time: 2 days

---

## Goal & context

The brief (§9) is explicit:

> *"Visual validation: Does the rendered interface match the applicable visual expectations, and are there relevant layout or presentation defects?*
>
> *Visual validation, for example, requires an appropriate visual reference or a clearly defined set of visual expectations. A screenshot comparison alone cannot determine whether an interface is semantically correct."*

The audit found visual validation is **entirely absent**:
- No `engine/visual/` module
- `observer.py:3, 19` explicitly says "no visual AI, no LLM calls"
- Screenshots are captured as evidence (`evidence_service.py:76-191`) but never compared or analyzed
- Action 02 declared `VisualRunner` as a stub returning `"unverified"` with "Visual validation not yet implemented. See action 10."

**This chunk builds the `VisualValidator`:**
1. Accepts a `visual_reference` artifact (screenshot + a11y tree from a known-good baseline)
2. Computes a structural diff against the post-action screenshot (pixel diff + layout diff + a11y tree diff)
3. Optionally invokes a VLM (vision-language model) for "does this look broken" classification
4. Returns a structured `VisualValidationResult` with defect classification

The brief's caveat is critical: "A screenshot comparison alone cannot determine whether an interface is semantically correct." So this chunk goes beyond pixel-diff — it includes a11y tree diff and VLM classification.

This is Action 10 because the brief lists visual validation as one of the 5 modes, and it's currently 0% implemented.

---

## Files to touch

- `backend/app/engine/visual/__init__.py` — new sub-package
- `backend/app/engine/visual/validator.py` — the main validator
- `backend/app/engine/visual/diff.py` — pixel + layout diff
- `backend/app/engine/visual/a11y_diff.py` — accessibility tree diff
- `backend/app/engine/visual/vlm_client.py` — VLM call for semantic classification
- `backend/app/engine/visual/schemas.py` — `VisualReference`, `VisualValidationResult`, `VisualDefect`
- `backend/app/modules/validation/visual_runner.py` — replace the stub from action 02
- `backend/app/modules/validation/models.py` — add `VisualReference` storage model
- `backend/alembic/versions/0NN_add_visual_references.py` — migration
- `backend/app/api/routes/flows.py` — `POST /api/v1/flows/{id}/visual-reference` to upload a baseline
- `backend/app/api/routes/executions.py` — include visual results in the report
- `backend/app/engine/ai/provider.py` — add VLM support (image input)
- `backend/app/config/settings.py` — `VLM_ENABLED: bool = False`, `VLM_MODEL`, `VLM_API_KEY`
- `frontend/components/executions/evidence-viewer.tsx` — render visual diff in a new "Visual Diff" tab
- `backend/tests/unit/test_visual_validator.py` — new

---

## Step-by-step spec

1. **Define the schemas.** In `backend/app/engine/visual/schemas.py`:
   ```python
   class VisualReference(BaseModel):
       id: uuid.UUID
       flow_id: uuid.UUID
       screenshot_url: str               # the baseline screenshot (S3)
       a11y_tree: dict                    # baseline accessibility tree
       viewport: dict                     # {"width": 1280, "height": 720}
       captured_at: datetime
       label: str                         # human-readable name e.g. "Dashboard - logged in as admin"
   
   class VisualDefect(BaseModel):
       type: Literal[
           "layout_shift",          # element moved significantly from baseline
           "element_missing",        # element in baseline, not in current
           "element_added",          # element in current, not in baseline
           "color_change",           # significant color shift
           "text_overflow",          # text extends beyond container
           "overlap",                # elements overlap that shouldn't
           "broken_image",           # image failed to load
           "viewport_overflow",      # horizontal scroll appears
       ]
       severity: Literal["low", "medium", "high"]
       description: str
       bounding_box: dict | None         # {"x", "y", "width", "height"} of the affected region
       confidence: float                  # 0..1
   
   class VisualValidationResult(BaseModel):
       overall_status: Literal["passed", "failed", "unverified"]
       pixel_diff_percentage: float       # 0..100 — % of pixels that differ
       layout_diff_count: int             # number of layout-level differences
       a11y_diff_count: int               # number of accessibility-tree differences
       defects: list[VisualDefect]
       vlm_assessment: str | None         # natural-language assessment from the VLM
       vlm_confidence: float | None
       evidence_screenshot_url: str       # the current run's screenshot
       reference_screenshot_url: str      # the baseline screenshot
   ```

2. **Implement the pixel + layout diff.** In `backend/app/engine/visual/diff.py`:
   ```python
   from PIL import Image
   import io
   import numpy as np
   
   def compute_pixel_diff(baseline_bytes: bytes, current_bytes: bytes) -> dict:
       """Compute pixel-level diff between two screenshots.
       
       Returns: {
           "diff_percentage": float,  # 0..100
           "diff_image_bytes": bytes,  # visual diff overlay
           "regions": list[dict],  # bounding boxes of significant diffs
       }
       """
       baseline = np.array(Image.open(io.BytesIO(baseline_bytes)).convert("RGB"))
       current = np.array(Image.open(io.BytesIO(current_bytes)).convert("RGB"))
       
       if baseline.shape != current.shape:
           return {"diff_percentage": 100.0, "diff_image_bytes": current_bytes, "regions": []}
       
       diff = np.abs(baseline.astype(int) - current.astype(int))
       # Per-pixel diff > 30 (out of 255) is "significant"
       significant = (diff.sum(axis=2) > 30)
       diff_percentage = (significant.sum() / significant.size) * 100
       
       # Find bounding boxes of significant regions (cluster adjacent pixels)
       regions = _cluster_regions(significant)
       
       # Generate diff overlay (red where pixels differ)
       diff_overlay = current.copy()
       diff_overlay[significant] = [255, 0, 0]
       diff_image = Image.fromarray(diff_overlay)
       buf = io.BytesIO()
       diff_image.save(buf, format="PNG")
       
       return {
           "diff_percentage": float(diff_percentage),
           "diff_image_bytes": buf.getvalue(),
           "regions": regions,
       }
   
   def _cluster_regions(significant: np.ndarray) -> list[dict]:
       """Find bounding boxes of clusters of significant pixels."""
       # Simple connected-components or sliding-window approach
       # Return [{"x": int, "y": int, "width": int, "height": int}, ...]
       ...
   ```

3. **Implement the a11y tree diff.** In `backend/app/engine/visual/a11y_diff.py`:
   ```python
   def compute_a11y_diff(baseline_tree: dict, current_tree: dict) -> dict:
       """Compare accessibility trees for structural differences.
       
       Detects: missing elements, added elements, role changes, name changes.
       """
       baseline_nodes = _flatten_tree(baseline_tree)
       current_nodes = _flatten_tree(current_tree)
       
       # Match nodes by role + name (best-effort)
       baseline_keys = {(n.get("role"), n.get("name")) for n in baseline_nodes}
       current_keys = {(n.get("role"), n.get("name")) for n in current_nodes}
       
       missing = baseline_keys - current_keys
       added = current_keys - baseline_keys
       
       return {
           "missing_elements": list(missing),
           "added_elements": list(added),
           "diff_count": len(missing) + len(added),
       }
   ```

4. **Implement the VLM client.** In `backend/app/engine/visual/vlm_client.py`:
   ```python
   class VLMClient:
       def __init__(self, provider, model: str):
           self.provider = provider
           self.model = model
       
       async def assess_visual_defects(
           self,
           baseline_screenshot_b64: str,
           current_screenshot_b64: str,
           diff_regions: list[dict],
           context: str,
       ) -> dict:
           """Ask the VLM to classify whether the diff regions represent real defects.
           
           Returns: {
               "assessment": str,  # natural-language
               "defects": list[VisualDefect],
               "confidence": float,
           }
           """
           prompt = (
               "You are assessing whether visual differences between two screenshots "
               "represent real defects. The first image is the baseline (known good). "
               "The second image is the current run. The diff regions are highlighted. "
               "Classify each region as: layout_shift, element_missing, element_added, "
               "color_change, text_overflow, overlap, broken_image, or viewport_overflow. "
               "If a region is a non-defect (e.g. anti-aliasing, dynamic content), say so. "
               "Provide a confidence level for each classification."
           )
           # Use the provider's image-input API
           ...
   ```

5. **Build the main validator.** In `backend/app/engine/visual/validator.py`:
   ```python
   class VisualValidator:
       def __init__(self, vlm_client: VLMClient | None = None):
           self.vlm_client = vlm_client
       
       async def validate(
           self,
           reference: VisualReference,
           current_screenshot_bytes: bytes,
           current_a11y_tree: dict,
           current_viewport: dict,
       ) -> VisualValidationResult:
           # 1. Download the baseline screenshot
           baseline_bytes = await self._download_screenshot(reference.screenshot_url)
           
           # 2. Compute pixel + layout diff
           pixel_diff = compute_pixel_diff(baseline_bytes, current_screenshot_bytes)
           
           # 3. Compute a11y tree diff
           a11y_diff = compute_a11y_diff(reference.a11y_tree, current_a11y_tree)
           
           # 4. Initial defect list from diffs
           defects = self._classify_diffs(pixel_diff, a11y_diff)
           
           # 5. VLM assessment (optional)
           vlm_assessment = None
           vlm_confidence = None
           if self.vlm_client and pixel_diff["diff_percentage"] > 0.5:
               vlm_result = await self.vlm_client.assess_visual_defects(
                   baseline_screenshot_b64=base64.b64encode(baseline_bytes).decode(),
                   current_screenshot_b64=base64.b64encode(current_screenshot_bytes).decode(),
                   diff_regions=pixel_diff["regions"],
                   context=f"Reference: {reference.label}",
               )
               vlm_assessment = vlm_result["assessment"]
               vlm_confidence = vlm_result["confidence"]
               # Merge VLM-classified defects with diff-detected ones
               defects = self._merge_defects(defects, vlm_result["defects"])
           
           # 6. Determine overall status
           high_severity_count = sum(1 for d in defects if d.severity == "high")
           medium_severity_count = sum(1 for d in defects if d.severity == "medium")
           
           if high_severity_count > 0:
               overall_status = "failed"
           elif medium_severity_count > 2:
               overall_status = "failed"
           elif defects:
               overall_status = "unverified"  # low-severity diffs — let the user decide
           else:
               overall_status = "passed"
           
           return VisualValidationResult(
               overall_status=overall_status,
               pixel_diff_percentage=pixel_diff["diff_percentage"],
               layout_diff_count=len(pixel_diff["regions"]),
               a11y_diff_count=a11y_diff["diff_count"],
               defects=defects,
               vlm_assessment=vlm_assessment,
               vlm_confidence=vlm_confidence,
               evidence_screenshot_url=...,  # upload current_screenshot_bytes to S3
               reference_screenshot_url=reference.screenshot_url,
           )
   ```

6. **Replace the VisualRunner stub.** In `backend/app/modules/validation/visual_runner.py`:
   ```python
   class VisualRunner:
       def __init__(self, criteria: SuccessCriteria):
           self.criteria = criteria
           # Initialize VLM client if enabled
           vlm_client = None
           if settings.VLM_ENABLED:
               provider = get_ai_provider()
               vlm_client = VLMClient(provider, settings.VLM_MODEL)
           self.validator = VisualValidator(vlm_client=vlm_client)
       
       async def run(self, request, plan) -> ValidationReport:
           # 1. Fetch the flow's visual reference (uploaded by user via API)
           reference = await self._get_visual_reference(plan.target_flow.id)
           if not reference:
               return ValidationReport(
                   overall_status="unverified",
                   failure_reason="No visual reference uploaded. Upload a baseline via POST /api/v1/flows/{id}/visual-reference.",
               )
           
           # 2. Run the flow (deterministic runner) to get the current state
           current_state = await self._execute_flow_steps(plan)
           
           # 3. Capture current screenshot + a11y tree
           current_screenshot = await self.browser.capture_screenshot()
           current_a11y = await self.browser.capture_a11y_tree()
           
           # 4. Run the validator
           result = await self.validator.validate(
               reference=reference,
               current_screenshot_bytes=current_screenshot,
               current_a11y_tree=current_a11y,
               current_viewport={"width": 1280, "height": 720},
           )
           
           # 5. Convert to ValidationReport
           return ValidationReport(
               overall_status=result.overall_status,
               results=[FlowValidationResult(
                   flow_id=plan.target_flow.id,
                   flow_name=plan.target_flow.name,
                   role="target",
                   status=result.overall_status,
                   duration_ms=0,
                   evidence_ids=[],
                   failure_reason=None if result.overall_status == "passed" else f"{len(result.defects)} visual defects detected",
                   state_changes={"visual_result": result.model_dump()},
               )],
           )
   ```

7. **Add the visual reference upload endpoint.** In `backend/app/api/routes/flows.py`:
   ```python
   @router.post("/flows/{flow_id}/visual-reference", status_code=201)
   async def upload_visual_reference(
       flow_id: uuid.UUID,
       file: UploadFile = File(...),
       label: str = Form(...),
       user: User = Depends(get_current_user),
       db: AsyncSession = Depends(get_db),
   ):
       """Upload a baseline screenshot for visual validation of this flow."""
       # Verify ownership
       # Upload the screenshot to S3
       # Capture the current a11y tree (or accept it from the upload)
       # Persist a VisualReference row
   ```

8. **Add VLM settings.** In `backend/app/config/settings.py`:
   ```python
   VLM_ENABLED: bool = False
   VLM_MODEL: str = "gpt-4o-mini"  # or any OpenAI-compatible vision model
   VLM_API_KEY: str = ""
   VLM_BASE_URL: str = "https://api.openai.com/v1"
   ```

9. **Render visual diff in the evidence viewer.** In `frontend/components/executions/evidence-viewer.tsx`, when the execution has `mode="visual"`, add a "Visual Diff" tab that shows:
    - The baseline screenshot on the left
    - The current screenshot on the right
    - The diff overlay in the middle (red where pixels differ)
    - The list of detected defects with severity badges
    - The VLM assessment text (if available)

10. **Write tests in `test_visual_validator.py`:**
    - `test_pixel_diff_identical_screenshots` — same image, 0% diff
    - `test_pixel_diff_shifted_button` — button moved 50px, detects the region
    - `test_a11y_diff_missing_button` — baseline has 5 buttons, current has 4, detects the missing one
    - `test_validator_returns_passed_when_no_defects` — clean run
    - `test_validator_returns_failed_when_high_severity_defect` — major layout shift
    - `test_validator_returns_unverified_when_vlm_disabled` — VLM off, low-severity diffs
    - `test_vlm_assessment_included_when_enabled` — VLM on, assessment text in result
    - `test_visual_runner_without_reference_returns_unverified` — no baseline uploaded

---

## Acceptance criteria

- [ ] `engine/visual/` package exists with `validator.py`, `diff.py`, `a11y_diff.py`, `vlm_client.py`, `schemas.py`.
- [ ] `VisualValidator.validate(reference, current_screenshot, current_a11y, viewport) -> VisualValidationResult` works end-to-end.
- [ ] Pixel diff detects layout shifts and returns bounding boxes of significant regions.
- [ ] A11y tree diff detects missing/added elements.
- [ ] VLM client works when `VLM_ENABLED=true` and is gracefully skipped when false.
- [ ] `VisualRunner` (from action 02's stub) now runs the validator and returns real results.
- [ ] `POST /api/v1/flows/{id}/visual-reference` endpoint uploads a baseline.
- [ ] Evidence viewer renders a "Visual Diff" tab with side-by-side screenshots + diff overlay + defect list.
- [ ] All 8 new tests pass.

---

## Anti-patterns to avoid

- **Do NOT rely on pixel diff alone.** The brief is explicit: "A screenshot comparison alone cannot determine whether an interface is semantically correct." Always include a11y tree diff. VLM is the semantic layer.
- **Do NOT make VLM a hard requirement.** Many deployments won't have a vision model configured. The validator must work with pixel + a11y diff alone; VLM is an enhancement.
- **Do NOT mark "passed" on the basis of low pixel diff alone.** Anti-aliasing, dynamic content, and timestamps can produce small pixel diffs that aren't defects. The validator should classify them as "unverified" or use the VLM to confirm.
- **Do NOT let the VLM make the final pass/fail decision.** The VLM proposes classifications; the deterministic validator applies the severity rules and decides overall status.
- **Do NOT block visual validation on VLM latency.** If the VLM is slow, the validator should return the pixel + a11y diff results immediately and attach the VLM assessment asynchronously (or skip it).
- **Do NOT upload screenshots larger than 1MB.** Downscale before S3 upload. Cost + latency matter.
- **Do NOT compare screenshots of different viewport sizes.** If the viewport differs, return "unverified" with a clear reason — pixel diff across viewports is meaningless.
- **Do NOT auto-upload the current screenshot as the new baseline.** Baselines are explicitly uploaded by the user. The validator never writes to `visual_references`.

---

## Dependencies & references

- **Read first:** `backend/app/modules/validation/models.py` (`ValidationMode` from action 02), `backend/app/modules/validation/visual_runner.py` (the stub from action 02), `backend/app/engine/browser/session.py` (screenshot + a11y capture methods), `backend/app/engine/ai/provider.py` (existing AI provider — extend with image input), `backend/app/modules/executions/evidence_service.py` (existing screenshot storage).
- **Predecessor chunks:** `00-overview.md`, `02-five-validation-modes.md` (declared visual as a stub).
- **Brief reference:** §9 "Visual validation" + §4 Stage 7 (Evidence and reporting — visual evidence).
