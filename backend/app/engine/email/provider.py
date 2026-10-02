"""Temporary email provider abstraction.

Kova's agent may need to receive email (signup verification, password reset).
Providers implement a minimal mailbox API. The first provider is an INTERNAL
SMTP mailbox: the execution environment runs or points to an SMTP server, and
the provider opens one IMAP/POP-free local mailbox per execution by listening
for deliveries on a per-mailbox queue.

Critical invariant (spec §9): a mailbox is created ONCE per execution; its
address becomes the persistent identity. Secrets (API keys, tokens) never
enter logs, events, or AI prompts.

Email links are UNTRUSTED navigation targets — the runtime re-validates every
URL through the existing SSRF policy before navigating.
"""

import asyncio
import logging
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.config.settings import settings
from app.engine.browser.session import _is_safe_url

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    sender: str
    subject: str
    body_text: str
    links: list[str] = field(default_factory=list)
    received_at: float = 0.0


@dataclass
class MailboxHandle:
    """Reference to a created mailbox. Address is the persistent identity."""

    mailbox_id: str
    address: str
    # Number of messages already consumed by this execution — advanced by
    # read_email so the next read gets the NEW message, not a stale one.
    consumed: int = 0


LINK_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


class TemporaryEmailProvider(ABC):
    """Abstract temporary mailbox provider."""

    @abstractmethod
    async def create_mailbox(self, hint: str | None = None) -> MailboxHandle:
        raise NotImplementedError

    @abstractmethod
    async def list_messages(self, mailbox: MailboxHandle) -> list[EmailMessage]:
        raise NotImplementedError

    @abstractmethod
    async def wait_for_message(
        self, mailbox: MailboxHandle, timeout_seconds: float = 60.0
    ) -> EmailMessage | None:
        raise NotImplementedError

    @abstractmethod
    async def close_mailbox(self, mailbox: MailboxHandle) -> None:
        raise NotImplementedError


def extract_links(body: str) -> list[str]:
    """Extract unique http(s) links from an email body, in order."""
    seen: set[str] = set()
    links: list[str] = []
    for match in LINK_RE.findall(body or ""):
        url = match.rstrip(".,;:!?")
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def validate_email_link(url: str, app_host: str | None = None) -> bool:
    """Security gate for links extracted from email (§10).

    Links from email are untrusted. A link is navigable only when it passes
    the same SSRF policy as every other navigation AND (when the app host is
    known) points at the target application's host — never a third-party or
    attacker-controlled redirect target smuggled through the mailbox.
    """
    if not _is_safe_url(url):
        return False
    if app_host:
        try:
            host = (urlparse(url).hostname or "").lower()
            target_host = app_host.split(":")[0].lower()
            if host != target_host and not host.endswith("." + target_host):
                return False
        except ValueError:
            return False
    return True


class HTTPPollMailboxProvider(TemporaryEmailProvider):
    """Internal provider backed by Kova's own test/support mail service.

    Talks to a small HTTP API (Kova fixture app or deployment-side mail service):
      POST /mailboxes                -> {"id", "address"}
      GET  /mailboxes/{id}/messages  -> [{"sender","subject","body","received_at"}]

    This keeps the agent integration provider-shaped without coupling Kova to a
    third-party temp-mail site (which would violate the safety rules — third
    party inboxes are publicly readable).
    """

    name = "http_poll"

    def __init__(self, base_url: str, api_key: str = ""):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._headers = (
            {"Authorization": f"Bearer {api_key}"} if api_key else {}
        )

    async def create_mailbox(self, hint: str | None = None) -> MailboxHandle:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base_url}/mailboxes",
                json={"hint": hint} if hint else {},
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
        mailbox = MailboxHandle(
            mailbox_id=str(data["id"]),
            address=str(data["address"]),
        )
        logger.info("Created temporary mailbox %s for execution identity", mailbox.mailbox_id)
        return mailbox

    async def list_messages(self, mailbox: MailboxHandle) -> list[EmailMessage]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._base_url}/mailboxes/{mailbox.mailbox_id}/messages",
                headers=self._headers,
            )
            resp.raise_for_status()
            raw = resp.json()
        messages: list[EmailMessage] = []
        for m in raw if isinstance(raw, list) else raw.get("messages", []):
            body = str(m.get("body", ""))
            messages.append(EmailMessage(
                sender=str(m.get("sender", "")),
                subject=str(m.get("subject", "")),
                body_text=body,
                links=extract_links(body),
                received_at=float(m.get("received_at", 0.0)),
            ))
        return messages

    async def wait_for_message(
        self, mailbox: MailboxHandle, timeout_seconds: float = 60.0
    ) -> EmailMessage | None:
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        poll = 1.0
        while asyncio.get_event_loop().time() < deadline:
            messages = await self.list_messages(mailbox)
            if messages:
                return messages[-1]
            await asyncio.sleep(poll)
        return None

    async def wait_for_new_message(
        self,
        mailbox: MailboxHandle,
        timeout_seconds: float = 60.0,
        min_index: int = 0,
        subject_keywords: tuple[str, ...] = (),
    ) -> EmailMessage | None:
        """Wait for a message beyond `min_index` (optionally matching keywords).

        `min_index` counts prior messages already consumed by this execution —
        lets the agent read the SECOND email (reset) without re-reading the
        first (verification). Keywords narrow to the right message class.
        """
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        poll = 1.0
        while asyncio.get_event_loop().time() < deadline:
            messages = await self.list_messages(mailbox)
            candidates = messages[min_index:]
            if subject_keywords:
                candidates = [
                    m for m in candidates
                    if any(kw in m.subject.lower() for kw in subject_keywords)
                ]
            if candidates:
                return candidates[-1]
            await asyncio.sleep(poll)
        return None

    async def close_mailbox(self, mailbox: MailboxHandle) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.request(
                    "DELETE",
                    f"{self._base_url}/mailboxes/{mailbox.mailbox_id}",
                    headers=self._headers,
                )
        except Exception as e:
            logger.debug("Mailbox close failed (ignored): %s", e)


def get_temp_email_provider() -> TemporaryEmailProvider | None:
    """Return the configured temp-email provider, or None when unavailable.

    Enabled when TEMPMAIL_SERVICE_URL is set. TEMPMAIL_API_KEY is supported for
    deployments that protect the mail service; the key never enters logs or AI
    prompts.
    """
    service_url = (getattr(settings, "TEMPMAIL_SERVICE_URL", "") or "").strip()
    if not service_url:
        return None
    return HTTPPollMailboxProvider(
        base_url=service_url,
        api_key=(getattr(settings, "TEMPMAIL_API_KEY", "") or "").strip(),
    )
