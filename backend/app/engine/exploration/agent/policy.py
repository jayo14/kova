from __future__ import annotations

import re


DANGEROUS_PATTERNS = [
    # Destructive mutations.
    r"\b(delete|destroy|erase|remove)\b",
    r"\b(reset|clear)\s+(all|data|account|history|cart|filters?)\b",
    # Money movement.
    r"\b(pay|payment|checkout|purchase|buy|subscribe|charge)\b",
    r"\b(upgrade|downgrade)\s+(plan|subscription)\b",
    r"\b(add|update|change)\s+(payment|card)\b",
    # Outbound communication and irreversible submission.
    r"\b(send|compose|reply|forward|share)\b.*\b(message|email|sms|invite)\b",
    r"\b(message|email)\s+(us|them|him|her|support|team|seller)\b",
    r"\b(submit|place\s+order)\b",
    r"\bapply\s+(now|for\s+(this\s+)?(job|position|role))\b",
    r"\bregister\s+(an?\s+)?account\b",
    r"\bsign\s?up\b",
    # Session and subscription teardown.
    r"\b(log\s?out|sign\s?out|signout)\b",
    r"\b(unsubscribe|cancel\s+(subscription|plan|account))\b",
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
        if t == "submit":
            return False
    return True
