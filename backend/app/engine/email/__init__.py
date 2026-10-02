"""Temporary email integration for agent email workflows.

Providers create isolated mailboxes whose addresses become the execution's
persistent identity. Links extracted from email are untrusted: the runtime
validates them against the same SSRF/host policy as all navigation
(`validate_email_link`) before the browser ever opens one.
"""

from app.engine.email.provider import (
    EmailMessage,
    HTTPPollMailboxProvider,
    MailboxHandle,
    TemporaryEmailProvider,
    extract_links,
    get_temp_email_provider,
    validate_email_link,
)

__all__ = [
    "EmailMessage",
    "HTTPPollMailboxProvider",
    "MailboxHandle",
    "TemporaryEmailProvider",
    "extract_links",
    "get_temp_email_provider",
    "validate_email_link",
]
