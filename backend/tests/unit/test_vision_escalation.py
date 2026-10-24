import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.engine.visual.vlm_client import VLMClient
from app.engine.visual.set_of_marks import capture_set_of_marks


def test_has_vision_capability_logic():
    # No API key -> False
    client = VLMClient(model="gpt-4o", api_key="")
    assert client.has_vision_capability() is False

    # Text-only model -> False
    client_text = VLMClient(model="openai/gpt-oss-120b", api_key="sk-test")
    assert client_text.has_vision_capability() is False

    # Vision-capable models -> True
    client_vision1 = VLMClient(model="gpt-4o", api_key="sk-test")
    assert client_vision1.has_vision_capability() is True

    client_vision2 = VLMClient(model="gemini-2.5-flash", api_key="sk-test")
    assert client_vision2.has_vision_capability() is True

    client_vision3 = VLMClient(model="claude-3-7-sonnet", api_key="sk-test")
    assert client_vision3.has_vision_capability() is True


@pytest.mark.asyncio
async def test_escalate_set_of_marks_skips_when_no_vision():
    client = VLMClient(model="openai/gpt-oss-120b", api_key="")
    res = await client.escalate_set_of_marks(
        screenshot_b64="fake_b64",
        marks=[{"index": 1, "name": "Submit", "selector": "#btn"}],
        objective="Click Submit button",
        reason="stuck",
    )
    assert res["skipped"] is True
    assert res["escalated"] is False
    assert res["reason"] == "no_vision_capability"
    assert res["selected_mark"] is None


@pytest.mark.asyncio
async def test_escalate_set_of_marks_with_mock_vlm_response():
    client = VLMClient(model="gpt-4o", api_key="sk-valid-key")
    marks = [
        {"index": 1, "type": "button", "name": "Cancel", "selector": "#cancel-btn"},
        {"index": 2, "type": "button", "name": "Confirm Action", "selector": "div.custom-btn"},
    ]

    mock_resp_json = {
        "choices": [
            {
                "message": {
                    "content": '{"selected_mark": 2, "action": "click", "target_name": "Confirm Action", "reasoning": "Target matches confirmation", "confidence": 0.95}'
                }
            }
        ]
    }

    mock_http_response = MagicMock()
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = mock_resp_json
    mock_http_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_http_response)):
        res = await client.escalate_set_of_marks(
            screenshot_b64="valid_base64_img",
            marks=marks,
            objective="Confirm the custom dialog action",
            reason="ambiguous_target",
        )

    assert res["escalated"] is True
    assert res["skipped"] is False
    assert res["selected_mark"] == 2
    assert res["matched_element"]["name"] == "Confirm Action"
    assert res["matched_element"]["selector"] == "div.custom-btn"
    assert res["confidence"] == 0.95


@pytest.mark.asyncio
async def test_capture_set_of_marks_generates_marks():
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_browser.page = mock_page
    mock_page.evaluate = AsyncMock()
    mock_browser.screenshot = AsyncMock(return_value=b"fake_png_data")

    elements = [
        {"type": "button", "name": "Login", "selector": "#login", "bounding_box": {"x": 10, "y": 20, "width": 80, "height": 30}},
        {"type": "link", "name": "Help", "selector": "#help", "bounding_box": {"x": 0, "y": 0, "width": 0, "height": 0}}, # zero size ignored
    ]

    png_bytes, marks = await capture_set_of_marks(mock_browser, elements)
    assert png_bytes == b"fake_png_data"
    assert len(marks) == 1
    assert marks[0]["index"] == 1
    assert marks[0]["name"] == "Login"
    assert marks[0]["x"] == 10
    assert marks[0]["width"] == 80
    mock_page.evaluate.assert_called()
