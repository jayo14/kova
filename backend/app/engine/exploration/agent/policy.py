from __future__ import annotations

import re


DANGEROUS_PATTERNS = [
    r"\b(delete|remove|destroy|erase)\b",
    r"\b(pay|checkout|purchase|buy|subscribe|charge|billing)\b",
    r"\b(send|message|email|submit.*form|apply|register.*account)\b",
    r"\b(logout|sign out|signout)\b",
    r"\b(unsubscribe|cancel.*subscription)\b",
]


def is_dangerous_control(text: str | None, attributes: dict | None = None) -> bool:
    if not text and not attributes:
        return False
    haystack_parts = []
    if text:
        haystack_parts.append(str(text))
    if attributes:
        for k in ["role", "type", "name", "aria-label", "id", "class"]:
            if attributes.get(k):
                haystack_parts.append(str(attributes[k]))
    haystack = " ".join(haystack_parts).lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, haystack):
            return True
    return False


def is_safe_to_click(text: str | None, attributes: dict | None = None) -> bool:
    # Exploration is read-only by default
    if is_dangerous_control(text, attributes):
        return False
    # Also block explicit submit buttons in forms
    if attributes:
        t = str(attributes.get("type", "")).lower()
        tag = str(attributes.get("tag", "")).lower()
        if t == "submit" or tag == "input" and t == "submit":
            return False
    return True
