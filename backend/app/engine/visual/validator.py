from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from app.engine.visual.a11y_diff import compute_a11y_diff
from app.engine.visual.diff import compute_pixel_diff
from app.engine.visual.schemas import (
    VisualDefect,
    VisualReference,
    VisualValidationResult,
)
from app.engine.visual.vlm_client import VLMClient

logger = logging.getLogger(__name__)


class VisualValidator:
    def __init__(self, vlm_client: VLMClient | None = None):
        self.vlm_client = vlm_client

    async def _download_screenshot(self, screenshot_url: str) -> bytes:
        """Retrieve screenshot bytes from a URL, data URI, or local file."""
        if screenshot_url.startswith("data:image/"):
            # data:image/png;base64,...
            _, b64data = screenshot_url.split(",", 1)
            return base64.b64decode(b64data)

        if screenshot_url.startswith("http://") or screenshot_url.startswith("https://"):
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.get(screenshot_url)
                res.raise_for_status()
                return res.content

        # Local file path
        path = Path(screenshot_url)
        if path.exists():
            return path.read_bytes()

        # If it looks like raw base64
        try:
            return base64.b64decode(screenshot_url)
        except Exception:
            return b""

    def _classify_diffs(
        self, pixel_diff: dict[str, Any], a11y_diff: dict[str, Any]
    ) -> list[VisualDefect]:
        """Convert pixel clusters and a11y tree diffs into structured VisualDefects."""
        defects: list[VisualDefect] = []

        # 1. Accessibility missing elements (high severity)
        for missing in a11y_diff.get("missing_elements", []):
            role = missing.get("role", "element")
            name = missing.get("name", "")
            defects.append(
                VisualDefect(
                    type="element_missing",
                    severity="high",
                    description=f"Expected {role} '{name}' is missing from the rendered view",
                    confidence=0.95,
                )
            )

        # 2. Accessibility added elements (medium severity)
        for added in a11y_diff.get("added_elements", []):
            role = added.get("role", "element")
            name = added.get("name", "")
            defects.append(
                VisualDefect(
                    type="element_added",
                    severity="medium",
                    description=f"Unexpected {role} '{name}' appeared in the rendered view",
                    confidence=0.85,
                )
            )

        # 3. Pixel diff regions
        diff_pct = pixel_diff.get("diff_percentage", 0.0)
        regions = pixel_diff.get("regions", [])

        if diff_pct > 0.0:
            for region in regions:
                w = region.get("width", 0)
                h = region.get("height", 0)
                area = w * h
                # Major region layout shift
                if area > 40000 or diff_pct > 10.0:
                    severity = "high"
                elif area > 5000 or diff_pct > 2.0:
                    severity = "medium"
                else:
                    severity = "low"

                defects.append(
                    VisualDefect(
                        type="layout_shift" if severity in ("high", "medium") else "color_change",
                        severity=severity,
                        description=f"Visual difference of {w}x{h}px detected at ({region.get('x')}, {region.get('y')})",
                        bounding_box=region,
                        confidence=0.9,
                    )
                )

            # If pixel diff exists but no discrete regions clustered
            if not regions and diff_pct > 0.1:
                defects.append(
                    VisualDefect(
                        type="color_change",
                        severity="low" if diff_pct < 1.0 else "medium",
                        description=f"Global pixel diff of {diff_pct:.2f}% detected across screenshot",
                        confidence=0.8,
                    )
                )

        return defects

    def _merge_defects(
        self, diff_defects: list[VisualDefect], vlm_defects: list[VisualDefect]
    ) -> list[VisualDefect]:
        """Merge rule-based diff defects with semantic VLM defects without duplicates."""
        merged = list(diff_defects)
        existing_descs = {d.description.lower() for d in merged}
        for vd in vlm_defects:
            if vd.description.lower() not in existing_descs:
                merged.append(vd)
        return merged

    async def validate(
        self,
        reference: VisualReference,
        current_screenshot_bytes: bytes,
        current_a11y_tree: dict | list,
        current_viewport: dict | None = None,
    ) -> VisualValidationResult:
        """Validate rendered UI against baseline visual reference using pixel diff, a11y tree diff, and optional VLM."""
        # 1. Download/obtain baseline screenshot
        baseline_bytes = await self._download_screenshot(reference.screenshot_url)
        if not baseline_bytes:
            return VisualValidationResult(
                overall_status="unverified",
                pixel_diff_percentage=0.0,
                layout_diff_count=0,
                a11y_diff_count=0,
                defects=[],
                vlm_assessment="Reference screenshot could not be loaded",
                reference_screenshot_url=reference.screenshot_url,
            )

        # 2. Compute pixel diff
        pixel_diff = compute_pixel_diff(baseline_bytes, current_screenshot_bytes)

        # 3. Compute accessibility diff
        a11y_diff = compute_a11y_diff(reference.a11y_tree, current_a11y_tree)

        # 4. Classify detected diffs
        defects = self._classify_diffs(pixel_diff, a11y_diff)

        # 5. Optional VLM assessment
        vlm_assessment = None
        vlm_confidence = None
        if self.vlm_client and pixel_diff["diff_percentage"] > 0.5:
            try:
                baseline_b64 = base64.b64encode(baseline_bytes).decode()
                current_b64 = base64.b64encode(current_screenshot_bytes).decode()
                vlm_result = await self.vlm_client.assess_visual_defects(
                    baseline_screenshot_b64=baseline_b64,
                    current_screenshot_b64=current_b64,
                    diff_regions=pixel_diff.get("regions", []),
                    context=f"Reference label: {reference.label}",
                )
                vlm_assessment = vlm_result.get("assessment")
                vlm_confidence = vlm_result.get("confidence")
                if vlm_result.get("defects"):
                    defects = self._merge_defects(defects, vlm_result["defects"])
            except Exception as e:
                logger.warning("VLM assessment call failed: %s", e)

        # 6. Determine overall status per §9 spec
        high_severity_count = sum(1 for d in defects if d.severity == "high")
        medium_severity_count = sum(1 for d in defects if d.severity == "medium")

        if high_severity_count > 0:
            overall_status = "failed"
        elif medium_severity_count > 2:
            overall_status = "failed"
        elif defects:
            overall_status = "unverified"
        else:
            overall_status = "passed"

        diff_image_b64 = (
            f"data:image/png;base64,{base64.b64encode(pixel_diff['diff_image_bytes']).decode()}"
            if pixel_diff.get("diff_image_bytes")
            else None
        )

        return VisualValidationResult(
            overall_status=overall_status,
            pixel_diff_percentage=pixel_diff["diff_percentage"],
            layout_diff_count=len(pixel_diff.get("regions", [])),
            a11y_diff_count=a11y_diff["diff_count"],
            defects=defects,
            vlm_assessment=vlm_assessment,
            vlm_confidence=vlm_confidence,
            evidence_screenshot_url="",
            reference_screenshot_url=reference.screenshot_url,
            diff_image_url=diff_image_b64,
        )
