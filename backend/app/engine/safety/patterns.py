import re

# High-confidence destructive patterns (case-insensitive substring match)
DESTRUCTIVE_KEYWORDS = {
    "delete", "remove", "destroy", "purge", "drop",
    "permanently delete", "wipe", "erase",
    "cancel subscription", "cancel account", "close account", "deactivate",
    "pay", "checkout", "purchase", "place order", "submit payment",
    "confirm payment", "buy now", "charge",
    "send money", "transfer funds", "withdraw",
}

# Regex patterns for more nuanced matching
DESTRUCTIVE_REGEXES = [
    re.compile(r"\bdelete\s+(user|account|project|file|record)s?\b", re.IGNORECASE),
    re.compile(r"\b(permanently|forever)\s+(delete|remove)\b", re.IGNORECASE),
    re.compile(r"\b(cancel|terminate)\s+(subscription|account|plan)\b", re.IGNORECASE),
    re.compile(r"\b(pay|charge|purchase)\s+\$?\d+", re.IGNORECASE),
    re.compile(r"\bconfirm\s+(delete|payment|purchase|order)\b", re.IGNORECASE),
]

# Action types that can be destructive (not just click — also form-submit, file-upload)
DESTRUCTIVE_ACTION_TYPES = {"click", "submit", "upload"}


def is_destructive(action_type: str, target_label: str | None, target_selector: str | None) -> bool:
    """Return True if this action appears destructive based on its label or selector."""
    if action_type not in DESTRUCTIVE_ACTION_TYPES:
        return False

    text = (target_label or "").lower()
    selector = (target_selector or "").lower()

    for kw in DESTRUCTIVE_KEYWORDS:
        if kw in text or kw in selector:
            return True

    for pattern in DESTRUCTIVE_REGEXES:
        if pattern.search(text) or pattern.search(selector):
            return True

    return False
