import base64
import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, ImageDraw

from app.engine.visual.a11y_diff import compute_a11y_diff
from app.engine.visual.diff import compute_pixel_diff
from app.engine.visual.schemas import VisualDefect, VisualReference, VisualValidationResult
from app.engine.visual.validator import VisualValidator
from app.modules.validation.models import ValidationMode
from app.modules.validation.schemas import ValidationRequest
from app.modules.validation.visual_runner import VisualRunner


def make_test_image(
    width: int = 200,
    height: int = 100,
    color: tuple = (255, 255, 255),
    rect: list[int] | None = None,
    rect_color: tuple = (0, 0, 255),
) -> bytes:
    """Helper to generate in-memory PNG bytes for testing."""
    img = Image.new("RGB", (width, height), color)
    if rect:
        draw = ImageDraw.Draw(img)
        draw.rectangle(rect, fill=rect_color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_pixel_diff_identical_screenshots():
    """Identical screenshots produce 0% diff and empty regions."""
    img = make_test_image(rect=[20, 20, 80, 60])
    res = compute_pixel_diff(img, img)
    assert res["diff_percentage"] == 0.0
    assert len(res["regions"]) == 0


def test_pixel_diff_shifted_button():
    """A moved element is detected with positive diff percentage and bounding regions."""
    baseline = make_test_image(rect=[20, 20, 80, 60], rect_color=(255, 0, 0))
    current = make_test_image(rect=[90, 20, 150, 60], rect_color=(255, 0, 0))
    res = compute_pixel_diff(baseline, current)
    assert res["diff_percentage"] > 0.0
    assert len(res["regions"]) > 0


def test_a11y_diff_missing_button():
    """Missing node in current a11y tree is identified with diff count."""
    baseline_tree = {
        "children": [
            {"role": "button", "name": f"Btn {i}"} for i in range(5)
        ]
    }
    current_tree = {
        "children": [
            {"role": "button", "name": f"Btn {i}"} for i in range(4)
        ]
    }
    res = compute_a11y_diff(baseline_tree, current_tree)
    assert res["diff_count"] == 1
    assert len(res["missing_elements"]) == 1
    assert res["missing_elements"][0]["name"] == "Btn 4"
    assert len(res["added_elements"]) == 0


@pytest.mark.asyncio
async def test_validator_returns_passed_when_no_defects():
    """Clean run with identical visuals and identical a11y returns overall_status='passed'."""
    img = make_test_image(rect=[10, 10, 40, 40])
    b64_img = f"data:image/png;base64,{base64.b64encode(img).decode()}"
    a11y = {"children": [{"role": "button", "name": "Submit"}]}

    ref = VisualReference(
        flow_id=uuid.uuid4(),
        screenshot_url=b64_img,
        a11y_tree=a11y,
        viewport={"width": 200, "height": 100},
    )

    validator = VisualValidator(vlm_client=None)
    result = await validator.validate(
        reference=ref,
        current_screenshot_bytes=img,
        current_a11y_tree=a11y,
        current_viewport={"width": 200, "height": 100},
    )

    assert result.overall_status == "passed"
    assert result.pixel_diff_percentage == 0.0
    assert len(result.defects) == 0


@pytest.mark.asyncio
async def test_validator_returns_failed_when_high_severity_defect():
    """Missing key element from baseline produces high severity defect and overall_status='failed'."""
    img = make_test_image(rect=[10, 10, 40, 40])
    b64_img = f"data:image/png;base64,{base64.b64encode(img).decode()}"
    baseline_a11y = {"children": [{"role": "button", "name": "Checkout Now"}]}
    current_a11y = {"children": []}  # button missing!

    ref = VisualReference(
        flow_id=uuid.uuid4(),
        screenshot_url=b64_img,
        a11y_tree=baseline_a11y,
    )

    validator = VisualValidator(vlm_client=None)
    result = await validator.validate(
        reference=ref,
        current_screenshot_bytes=img,
        current_a11y_tree=current_a11y,
    )

    assert result.overall_status == "failed"
    assert any(d.type == "element_missing" and d.severity == "high" for d in result.defects)


@pytest.mark.asyncio
async def test_validator_returns_unverified_when_low_severity_diff():
    """Small minor pixel diff with no missing semantic nodes returns 'unverified'."""
    baseline = make_test_image(width=100, height=100, color=(255, 255, 255), rect=[10, 10, 14, 14], rect_color=(0, 0, 100))
    current = make_test_image(width=100, height=100, color=(255, 255, 255), rect=[10, 10, 14, 14], rect_color=(0, 0, 150))
    b64_baseline = f"data:image/png;base64,{base64.b64encode(baseline).decode()}"
    a11y = {"children": [{"role": "text", "name": "Logo"}]}

    ref = VisualReference(
        flow_id=uuid.uuid4(),
        screenshot_url=b64_baseline,
        a11y_tree=a11y,
    )

    validator = VisualValidator(vlm_client=None)
    result = await validator.validate(
        reference=ref,
        current_screenshot_bytes=current,
        current_a11y_tree=a11y,
    )

    # Minor color difference without high severity defects returns unverified
    assert result.overall_status == "unverified"
    assert any(d.severity == "low" for d in result.defects)


@pytest.mark.asyncio
async def test_vlm_assessment_included_when_enabled():
    """When VLM client is provided and diff > 0.5%, assessment is incorporated."""
    baseline = make_test_image(width=100, height=100, rect=[10, 10, 50, 50], rect_color=(255, 0, 0))
    current = make_test_image(width=100, height=100, rect=[40, 10, 80, 50], rect_color=(255, 0, 0))
    b64_baseline = f"data:image/png;base64,{base64.b64encode(baseline).decode()}"

    ref = VisualReference(
        flow_id=uuid.uuid4(),
        screenshot_url=b64_baseline,
        a11y_tree={},
    )

    mock_vlm = MagicMock()
    mock_vlm.assess_visual_defects = AsyncMock(
        return_value={
            "assessment": "Button shifted right by 30px, causing misalignment with header.",
            "defects": [
                VisualDefect(
                    type="layout_shift",
                    severity="high",
                    description="Button alignment broken",
                    confidence=0.92,
                )
            ],
            "confidence": 0.92,
        }
    )

    validator = VisualValidator(vlm_client=mock_vlm)
    result = await validator.validate(
        reference=ref,
        current_screenshot_bytes=current,
        current_a11y_tree={},
    )

    assert result.overall_status == "failed"
    assert "Button shifted right" in (result.vlm_assessment or "")
    assert result.vlm_confidence == 0.92
    mock_vlm.assess_visual_defects.assert_called_once()


@pytest.mark.asyncio
async def test_visual_runner_without_reference_returns_unverified():
    """Visual runner without uploaded baseline returns 'unverified' and prompt to upload."""
    runner = VisualRunner(db=None)
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        mode=ValidationMode.VISUAL,
    )
    report = await runner.run(req)

    assert report.overall_status == "unverified"
    assert "No visual reference uploaded" in (report.failure_reason or "")
    assert "POST /api/v1/flows/{id}/visual-reference" in (report.failure_reason or "")
