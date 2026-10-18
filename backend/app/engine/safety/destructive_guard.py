from typing import Any

from app.engine.safety.patterns import is_destructive
from app.modules.projects.schemas import SafetyRestrictions


class DestructiveActionBlocked(Exception):
    def __init__(self, action_label: str, reason: str):
        self.action_label = action_label
        self.reason = reason
        super().__init__(f"Destructive action blocked: {action_label} — {reason}")


class DestructiveActionGuard:
    def __init__(self, safety_restrictions: SafetyRestrictions | dict | Any | None = None):
        if isinstance(safety_restrictions, dict):
            self.safety = SafetyRestrictions(**safety_restrictions)
        elif isinstance(safety_restrictions, SafetyRestrictions):
            self.safety = safety_restrictions
        else:
            self.safety = SafetyRestrictions()
        self.allowlist = set(self.safety.destructive_action_allowlist or [])

    def check(self, action_type: str, target_label: str | None, target_selector: str | None) -> None:
        """Raise DestructiveActionBlocked if the action is destructive AND not allowlisted."""
        if not is_destructive(action_type, target_label, target_selector):
            return

        # Check explicit allowlist (case-insensitive substring match)
        label_lower = (target_label or "").lower()
        selector_lower = (target_selector or "").lower()
        for allowed in self.allowlist:
            allowed_lower = allowed.lower()
            if allowed_lower and (allowed_lower in label_lower or allowed_lower in selector_lower):
                return

        # Not allowlisted — block
        reason = (
            f"Action '{target_label or target_selector}' is destructive "
            f"(matched pattern in action_type={action_type}). "
            f"To permit this action, add it to the project's "
            f"safety_restrictions.destructive_action_allowlist."
        )
        raise DestructiveActionBlocked(
            action_label=target_label or target_selector or action_type,
            reason=reason,
        )
