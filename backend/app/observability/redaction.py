"""Central data redaction filter for secrets and sensitive values."""

from __future__ import annotations

import logging
import re
from typing import Any

DEFAULT_REDACTION_KEYS: set[str] = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "set-cookie",
    "webhook_secret",
    "access_token",
    "refresh_token",
    "private_key",
    "credential",
    "dek",
    "wrapped_dek",
}

# Regex to redact auth headers, tokens, or credential strings in raw text
SENSITIVE_STRING_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE),
    re.compile(r"(kova_[a-f0-9]{32,64})", re.IGNORECASE),
    re.compile(
        r"((?:password|secret|token|api[_-]?key)\s*[:=]\s*[\"']?)([^\s\"',]+)([\"']?)",
        re.IGNORECASE,
    ),
]

REDACTED_STR = "***REDACTED***"


def _is_sensitive_key(key: str, sensitive_keys: set[str]) -> bool:
    key_lower = key.lower().replace("-", "_")
    if key_lower in sensitive_keys:
        return True
    parts = set(key_lower.split("_"))
    return any(sens in parts for sens in sensitive_keys)


def redact(obj: Any, keys_to_redact: set[str] | None = None) -> Any:
    """Recursively scrub sensitive keys and tokens from dicts, lists, and primitives."""
    sensitive_keys = {k.lower() for k in (keys_to_redact or DEFAULT_REDACTION_KEYS)}

    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and _is_sensitive_key(k, sensitive_keys):
                result[k] = REDACTED_STR
            else:
                result[k] = redact(v, sensitive_keys)
        return result

    if isinstance(obj, (list, tuple, set)):
        items = [redact(item, sensitive_keys) for item in obj]
        return type(obj)(items) if not isinstance(obj, set) else set(items)

    if isinstance(obj, str):
        redacted_text = obj
        for pat in SENSITIVE_STRING_PATTERNS:
            if "Bearer " in pat.pattern:
                redacted_text = pat.sub(r"\1***REDACTED***", redacted_text)
            elif "password" in pat.pattern:
                redacted_text = pat.sub(r"\1***REDACTED***\3", redacted_text)
            else:
                redacted_text = pat.sub(r"***REDACTED***", redacted_text)
        return redacted_text

    return obj


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs sensitive fields from log messages and attributes."""

    def __init__(self, keys_to_redact: set[str] | None = None):
        super().__init__()
        self.keys_to_redact = keys_to_redact or DEFAULT_REDACTION_KEYS

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg, self.keys_to_redact)
        elif isinstance(record.msg, dict):
            record.msg = redact(record.msg, self.keys_to_redact)

        if record.args:
            if isinstance(record.args, dict):
                record.args = redact(record.args, self.keys_to_redact)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact(arg, self.keys_to_redact) for arg in record.args)
            elif isinstance(record.args, list):
                record.args = [redact(arg, self.keys_to_redact) for arg in record.args]

        for attr in ("extra", "metadata", "payload", "detail"):
            if hasattr(record, attr):
                val = getattr(record, attr)
                setattr(record, attr, redact(val, self.keys_to_redact))

        return True
