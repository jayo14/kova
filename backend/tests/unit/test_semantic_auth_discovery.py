import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engine.ai.schemas import AuthEntranceSemanticResult, AuthFormSemanticResult
from app.engine.browser.auth import (
    find_auth_entrance_semantically,
    find_auth_inputs_semantically,
    perform_login,
)
from app.engine.exploration.explorer import ExplorationEngine


@pytest.mark.asyncio
async def test_find_auth_entrance_semantically_keyword_fallback():
    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    candidates = [
        {"index": 0, "tagName": "a", "text": "About Us", "href": "/about", "role": "", "ariaLabel": ""},
        {"index": 1, "tagName": "button", "text": "Get Started", "href": "", "role": "button", "ariaLabel": ""},
        {"index": 2, "tagName": "a", "text": "Pricing", "href": "/pricing", "role": "", "ariaLabel": ""},
    ]
    mock_page.evaluate = AsyncMock(return_value=candidates)
    mock_loc = MagicMock()
    mock_loc.is_visible = AsyncMock(return_value=True)
    mock_loc.click = AsyncMock()
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_loc))

    success = await find_auth_entrance_semantically(mock_page, provider=None, is_signup=True)
    assert success is True
    mock_loc.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_auth_entrance_semantically_with_ai_provider():
    mock_page = MagicMock()
    mock_page.url = "https://custom-app.com"
    candidates = [
        {"index": 0, "tagName": "button", "text": "Take a Quiz", "href": "", "role": "button", "ariaLabel": ""},
        {"index": 1, "tagName": "button", "text": "Explore", "href": "", "role": "button", "ariaLabel": ""},
    ]
    mock_page.evaluate = AsyncMock(return_value=candidates)
    mock_loc = MagicMock()
    mock_loc.is_visible = AsyncMock(return_value=True)
    mock_loc.click = AsyncMock()
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_loc))

    mock_provider = MagicMock()
    mock_provider.generate_structured = AsyncMock(
        return_value=AuthEntranceSemanticResult(
            entrance_index=0,
            confidence=0.9,
            reasoning="Take a Quiz enters user flow",
        )
    )

    success = await find_auth_entrance_semantically(mock_page, provider=mock_provider, is_signup=True)
    assert success is True
    mock_page.locator.assert_called_with('[data-kova-entrance-candidate="0"]')


@pytest.mark.asyncio
async def test_find_auth_inputs_semantically_layout_and_at_placeholder():
    mock_page = MagicMock()
    mock_page.frames = []
    candidates = [
        {
            "index": 0,
            "tagName": "input",
            "type": "text",
            "name": "custom_field_1",
            "id": "inp-1",
            "placeholder": "name@domain.com",
            "ariaLabel": "",
            "labelText": "",
            "role": "",
            "text": "",
        },
        {
            "index": 1,
            "tagName": "input",
            "type": "text",
            "name": "secret_key",
            "id": "inp-2",
            "placeholder": "Enter secret code",
            "ariaLabel": "",
            "labelText": "Security PIN",
            "role": "",
            "text": "",
        },
    ]
    mock_page.evaluate = AsyncMock(return_value=candidates)
    mock_loc_email = MagicMock()
    mock_loc_pwd = MagicMock()

    def locator_side_effect(selector):
        if "0" in selector:
            return MagicMock(first=mock_loc_email)
        return MagicMock(first=mock_loc_pwd)

    mock_page.locator = MagicMock(side_effect=locator_side_effect)

    name_loc, email_loc, pwd_loc, scope = await find_auth_inputs_semantically(mock_page, provider=None, is_signup=False)
    assert email_loc is not None
    assert pwd_loc is not None


@pytest.mark.asyncio
async def test_explorer_has_visible_auth_inputs_in_modal():
    explorer = ExplorationEngine()
    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    mock_page.frames = []

    mock_dialog_loc = MagicMock()
    mock_dialog_loc.is_visible = AsyncMock(return_value=True)

    def locator_side_effect(selector):
        loc = MagicMock()
        if "dialog" in selector or "form" in selector:
            loc.first.is_visible = AsyncMock(return_value=True)
        else:
            loc.first.is_visible = AsyncMock(return_value=False)
        return loc

    mock_page.locator = MagicMock(side_effect=locator_side_effect)

    has_inputs = await explorer._has_visible_auth_inputs(mock_page)
    assert has_inputs is True
