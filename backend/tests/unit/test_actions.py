"""Unit tests for action validation and masking.

Tests the validate_action function and sensitive value masking.
No browser required.
"""

import pytest

from app.engine.browser.actions import (
    Action,
    ActionExecutionError,
    ActionType,
    ActionValidationError,
    ActionTarget,
    mask_sensitive,
    sanitize_for_log,
    validate_action,
)


# --- mask_sensitive ---


def test_mask_sensitive_short():
    """Short strings (<=4 chars) are fully masked."""
    assert mask_sensitive("ab") == "**"
    assert mask_sensitive("secret") == "s****t"


def test_mask_sensitive_empty():
    """Empty string stays empty."""
    assert mask_sensitive("") == ""


def test_mask_sensitive_single_char():
    """Single char is masked."""
    assert mask_sensitive("a") == "*"


def test_mask_sensitive_exactly_4():
    """Exactly 4 chars fully masked."""
    assert mask_sensitive("test") == "****"


# --- sanitize_for_log ---


def test_sanitizes_value_field():
    """Value field is masked in output."""
    result = sanitize_for_log({"type": "type", "value": "password123"})
    assert result["value"] == "p*********3"
    assert result["type"] == "type"


def test_sanitizes_nested_value():
    """Value inside target is NOT masked (target has no value)."""
    result = sanitize_for_log({
        "type": "click",
        "target": {"role": "button", "name": "Submit"},
    })
    assert result["target"]["name"] == "Submit"


def test_preserves_non_sensitive():
    """Non-sensitive fields pass through unchanged."""
    result = sanitize_for_log({
        "type": "navigate",
        "direction": "down",
        "key": "Enter",
    })
    assert result["type"] == "navigate"
    assert result["direction"] == "down"
    assert result["key"] == "Enter"


# --- ActionTarget ---


def test_action_target_is_empty():
    """Empty target reports is_empty True."""
    t = ActionTarget()
    assert t.is_empty() is True


def test_action_target_not_empty():
    """Target with role set is not empty."""
    t = ActionTarget(role="button")
    assert t.is_empty() is False


def test_action_target_to_dict_excludes_empty():
    """to_dict excludes empty fields."""
    t = ActionTarget(role="button", name="Submit")
    d = t.to_dict()
    assert d == {"role": "button", "name": "Submit"}
    assert "label" not in d


# --- validate_action ---


def test_validate_navigate():
    """Valid navigate action."""
    action = validate_action({"type": "navigate", "value": "http://example.com"})
    assert action.type == ActionType.NAVIGATE
    assert action.value == "http://example.com"


def test_validate_click():
    """Valid click action with target."""
    action = validate_action({
        "type": "click",
        "target": {"role": "button", "name": "Submit"},
    })
    assert action.type == ActionType.CLICK
    assert action.target.role == "button"
    assert action.target.name == "Submit"


def test_validate_type():
    """Valid type action."""
    action = validate_action({
        "type": "type",
        "target": {"label": "Email"},
        "value": "test@example.com",
    })
    assert action.type == ActionType.TYPE
    assert action.value == "test@example.com"


def test_validate_clear():
    """Valid clear action."""
    action = validate_action({
        "type": "clear",
        "target": {"css": "#email"},
    })
    assert action.type == ActionType.CLEAR


def test_validate_press():
    """Valid press action."""
    action = validate_action({"type": "press", "key": "Enter"})
    assert action.type == ActionType.PRESS
    assert action.key == "Enter"


def test_validate_scroll():
    """Valid scroll action."""
    action = validate_action({"type": "scroll", "direction": "down", "amount": 300})
    assert action.type == ActionType.SCROLL
    assert action.direction == "down"
    assert action.amount == 300


def test_validate_missing_type():
    """Missing type raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({})
    assert "missing required field 'type'" in str(exc_info.value)


def test_validate_invalid_type():
    """Invalid type raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "invalid"})
    assert "invalid type" in str(exc_info.value)


def test_validate_navigate_missing_url():
    """Navigate without value raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "navigate"})
    assert "requires 'value'" in str(exc_info.value)


def test_validate_navigate_invalid_url():
    """Navigate with non-URL value raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "navigate", "value": "not-a-url"})
    assert "not a valid URL" in str(exc_info.value)


def test_validate_click_no_target():
    """Click without target raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "click"})
    assert "requires a target" in str(exc_info.value)


def test_validate_type_no_target():
    """Type without target raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "type", "value": "hello"})
    assert "requires a target" in str(exc_info.value)


def test_validate_type_no_value():
    """Type without value raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "type", "target": {"label": "Email"}})
    assert "requires 'value'" in str(exc_info.value)


def test_validate_press_no_key():
    """Press without key raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "press"})
    assert "requires 'key'" in str(exc_info.value)


def test_validate_scroll_invalid_direction():
    """Scroll with invalid direction raises error."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "scroll", "direction": "diagonal"})
    assert "must be 'up' or 'down'" in str(exc_info.value)


def test_validate_multiple_errors():
    """Multiple validation errors collected."""
    with pytest.raises(ActionValidationError) as exc_info:
        validate_action({"type": "unknown"})
    assert len(exc_info.value.errors) >= 1


# --- Action.to_dict ---


def test_action_to_dict_masks_value():
    """Action.to_dict masks sensitive values."""
    action = Action(
        type=ActionType.TYPE,
        target=ActionTarget(label="Password"),
        value="supersecret",
    )
    d = action.to_dict()
    assert d["value"] == "s*********t"


def test_action_to_dict_no_value():
    """Action.to_dict omits empty value."""
    action = Action(type=ActionType.CLICK, target=ActionTarget(role="button"))
    d = action.to_dict()
    assert "value" not in d


# --- ActionExecutionError ---


def test_action_execution_error():
    """ActionExecutionError carries structured info."""
    err = ActionExecutionError(
        action_type="click",
        message="Element not visible",
        error_code="not_visible",
        target={"role": "button", "name": "Submit"},
    )
    assert err.action_type == "click"
    assert err.error_code == "not_visible"
    assert err.target["name"] == "Submit"
