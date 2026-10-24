"""Fixture-backed temporary email provider for benchmark runs (§14, Prompt A)."""

import asyncio
import time
import httpx

from app.engine.email.provider import (
    EmailMessage,
    MailboxHandle,
    TemporaryEmailProvider,
    extract_links,
)


class FixtureEmailProvider(TemporaryEmailProvider):
    """TemporaryEmailProvider implementation reading from a fixture server's /api/inbox/{email}."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def create_mailbox(self, hint: str | None = None) -> MailboxHandle:
        addr = hint or "tester@kova.internal"
        return MailboxHandle(mailbox_id=addr, address=addr)

    async def list_messages(self, mailbox: MailboxHandle) -> list[EmailMessage]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/inbox/{mailbox.address}")
                if resp.status_code != 200:
                    return []
                data = resp.json()
                messages: list[EmailMessage] = []
                for item in data.get("messages", []):
                    code = item.get("code", "")
                    subject = item.get("subject", "Verification Code")
                    body = item.get("body", "") or f"Your verification code is {code}"
                    messages.append(
                        EmailMessage(
                            sender="fixture@kova.internal",
                            subject=subject,
                            body_text=body,
                            links=extract_links(body),
                            received_at=time.time(),
                        )
                    )
                if not messages and data.get("latest_code"):
                    code = data["latest_code"]
                    body = f"Your verification code is {code}"
                    messages.append(
                        EmailMessage(
                            sender="fixture@kova.internal",
                            subject="Verification Code",
                            body_text=body,
                            links=extract_links(body),
                            received_at=time.time(),
                        )
                    )
                return messages
        except Exception:
            return []

    async def wait_for_message(
        self, mailbox: MailboxHandle, timeout_seconds: float = 10.0
    ) -> EmailMessage | None:
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            msgs = await self.list_messages(mailbox)
            if msgs:
                return msgs[-1]
            await asyncio.sleep(0.2)
        return None

    async def close_mailbox(self, mailbox: MailboxHandle) -> None:
        pass
