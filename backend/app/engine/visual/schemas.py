import uuid
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


class VisualReference(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    flow_id: uuid.UUID
    screenshot_url: str               # the baseline screenshot (S3 or local/data URI)
    a11y_tree: dict = Field(default_factory=dict)  # baseline accessibility tree
    viewport: dict = Field(default_factory=lambda: {"width": 1280, "height": 720})
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    label: str = "Baseline"           # human-readable name e.g. "Dashboard - logged in as admin"


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
    bounding_box: dict[str, int] | None = None         # {"x", "y", "width", "height"} of the affected region
    confidence: float = 1.0                  # 0..1


class VisualValidationResult(BaseModel):
    overall_status: Literal["passed", "failed", "unverified"]
    pixel_diff_percentage: float       # 0..100 — % of pixels that differ
    layout_diff_count: int             # number of layout-level differences
    a11y_diff_count: int               # number of accessibility-tree differences
    defects: list[VisualDefect] = Field(default_factory=list)
    vlm_assessment: str | None = None  # natural-language assessment from the VLM
    vlm_confidence: float | None = None
    evidence_screenshot_url: str = ""  # the current run's screenshot
    reference_screenshot_url: str = "" # the baseline screenshot
    diff_image_url: str | None = None  # the visual diff overlay image URL/data
