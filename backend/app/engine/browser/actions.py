"""Structured browser actions.

Defines action types, validation, and models for the action executor.
Actions are the atomic units of browser interaction.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """Supported browser action types."""

    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    CLEAR = "clear"
    PRESS = "press"
    SCROLL = "scroll"
    BACK = "back"
    FORWARD = "forward"
    RELOAD = "reload"
    SELECT = "select"
    WAIT = "wait"
    CHECK = "check"
    UNCHECK = "uncheck"
    UPLOAD = "upload"


# Fields that may contain credentials/secrets — never logged
SENSITIVE_FIELDS = {"value", "password", "secret", "token", "api_key"}


class ActionValidationError(Exception):
    """Raised when an action fails validation."""

    def __init__(self, action_type: str, errors: list[str]):
        self.action_type = action_type
        self.errors = errors
        super().__init__(
            f"Validation failed for '{action_type}': {'; '.join(errors)}"
        )


class ActionExecutionError(Exception):
    """Raised when an action fails during execution."""

    def __init__(
        self,
        action_type: str,
        message: str,
        error_code: str = "",
        target: dict | None = None,
    ):
        self.action_type = action_type
        self.message = message
        self.error_code = error_code
        self.target = target or {}
        super().__init__(message)


@dataclass
class ActionTarget:
    """Target specification for an action.

    At least one field must be set to identify the target element.
    """

    role: str = ""
    name: str = ""
    label: str = ""
    test_id: str = ""
    text: str = ""
    css: str = ""

    def is_empty(self) -> bool:
        """Check if all target fields are empty."""
        return not any([self.role, self.name, self.label, self.test_id, self.text, self.css])

    def to_dict(self) -> dict[str, str]:
        """Convert to dict, excluding empty fields."""
        d = {}
        if self.role:
            d["role"] = self.role
        if self.name:
            d["name"] = self.name
        if self.label:
            d["label"] = self.label
        if self.test_id:
            d["test_id"] = self.test_id
        if self.text:
            d["text"] = self.text
        if self.css:
            d["css"] = self.css
        return d


@dataclass
class Action:
    """A structured browser action."""

    type: ActionType
    target: ActionTarget = field(default_factory=ActionTarget)
    value: str = ""
    direction: str = ""
    key: str = ""
    amount: int = 500

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization.

        Sensitive values are masked.
        """
        d: dict[str, Any] = {"type": self.type.value}
        if not self.target.is_empty():
            d["target"] = self.target.to_dict()
        if self.value:
            d["value"] = mask_sensitive(self.value)
        if self.direction:
            d["direction"] = self.direction
        if self.key:
            d["key"] = self.key
        if self.amount != 500:
            d["amount"] = self.amount
        return d


def mask_sensitive(value: str) -> str:
    """Mask sensitive values for logging/persistence.

    Returns the original value for short strings,
    masks everything except first/last char for longer strings.
    """
    if len(value) <= 4:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]


def sanitize_for_log(action_dict: dict) -> dict:
    """Create a copy with sensitive fields masked for logging."""
    sanitized = {}
    for key, val in action_dict.items():
        if key in SENSITIVE_FIELDS and isinstance(val, str):
            sanitized[key] = mask_sensitive(val)
        elif key == "target" and isinstance(val, dict):
            sanitized[key] = val.copy()
        elif key == "value" and isinstance(val, str):
            sanitized[key] = mask_sensitive(val)
        else:
            sanitized[key] = val
    return sanitized


# --- Validation ---


def validate_action(raw: dict) -> Action:
    """Validate a raw action dict and return a typed Action.

    Raises ActionValidationError on invalid input.
    """
    errors: list[str] = []

    # Type is required
    raw_type = raw.get("type", "")
    if not raw_type:
        errors.append("missing required field 'type'")
    try:
        action_type = ActionType(raw_type)
    except ValueError:
        valid = [t.value for t in ActionType]
        errors.append(f"invalid type '{raw_type}'; must be one of: {', '.join(valid)}")
        raise ActionValidationError(raw_type or "unknown", errors)

    # Validate target
    raw_target = raw.get("target")
    target = ActionTarget()
    if raw_target is not None:
        if not isinstance(raw_target, dict):
            errors.append("'target' must be an object")
        else:
            target = ActionTarget(
                role=raw_target.get("role", ""),
                name=raw_target.get("name", ""),
                label=raw_target.get("label", ""),
                test_id=raw_target.get("test_id", ""),
                text=raw_target.get("text", ""),
                css=raw_target.get("css", ""),
            )

    # Validate value
    raw_value = raw.get("value", "")
    if not isinstance(raw_value, str):
        errors.append("'value' must be a string")
        raw_value = ""

    # Validate direction
    raw_direction = raw.get("direction", "")
    if raw_direction and raw_direction not in ("up", "down", "left", "right"):
        errors.append(f"'direction' must be one of: up, down, left, right")

    # Validate key
    raw_key = raw.get("key", "")
    if not isinstance(raw_key, str):
        errors.append("'key' must be a string")
        raw_key = ""

    # Validate amount
    raw_amount = raw.get("amount", 500)
    if not isinstance(raw_amount, int) or raw_amount < 0:
        errors.append("'amount' must be a non-negative integer")
        raw_amount = 500

    # Action-specific validation
    if action_type == ActionType.NAVIGATE:
        if not raw_value:
            errors.append("'navigate' requires 'value' (URL)")
        elif not _is_valid_url(raw_value):
            errors.append(f"'value' is not a valid URL: {raw_value}")

    elif action_type in (ActionType.CLICK, ActionType.CLEAR, ActionType.CHECK, ActionType.UNCHECK):
        if target.is_empty():
            errors.append(f"'{action_type.value}' requires a target")

    elif action_type == ActionType.SELECT:
        if target.is_empty():
            errors.append("'select' requires a target")

    elif action_type == ActionType.UPLOAD:
        if target.is_empty():
            errors.append("'upload' requires a target")
        if not raw_value:
            errors.append("'upload' requires 'value' (file path)")

    elif action_type == ActionType.WAIT:
        pass  # target optional, amount or value used for delay

    elif action_type == ActionType.TYPE:
        if target.is_empty():
            errors.append("'type' requires a target")
        has_credential = bool(raw.get("credential_id"))
        if not raw_value and not has_credential:
            errors.append("'type' requires 'value' or 'credential_id'")
        # credential_field must be 'password' or 'email' when credential_id present
        cred_field = raw.get("credential_field")
        if has_credential and cred_field not in (None, "password", "email"):
            errors.append("'credential_field' must be 'password' or 'email'")

    elif action_type == ActionType.PRESS:
        if not raw_key:
            errors.append("'press' requires 'key' (e.g. 'Enter', 'Tab')")

    elif action_type == ActionType.SCROLL:
        if raw_direction and raw_direction not in ("up", "down"):
            errors.append("'scroll' direction must be 'up' or 'down'")

    elif action_type in (ActionType.BACK, ActionType.FORWARD, ActionType.RELOAD):
        pass  # No additional validation needed

    if errors:
        raise ActionValidationError(raw_type, errors)

    return Action(
        type=action_type,
        target=target,
        value=raw_value,
        direction=raw_direction,
        key=raw_key,
        amount=raw_amount,
    )


def _is_valid_url(value: str) -> bool:
    """Basic URL validation."""
    return bool(re.match(r"^https?://", value))
