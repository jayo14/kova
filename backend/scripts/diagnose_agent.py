"""Diagnostic: trace agent loop decisions against the fixture app."""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import uvicorn

from app.engine.ai.executor import AgentExecutor
from app.engine.ai.reasoner import AgentReasoner
from app.engine.browser.session import BrowserSession
from app.engine.credentials.models import Credential
from app.engine.credentials.store import CredentialStore
from app.engine.email.provider import HTTPPollMailboxProvider
from tests.agent_fixture import agent_app, mail_service


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_app(app):
    port = _get_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.4)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def main():
    async with _run_app(agent_app) as app_url, _run_app(mail_service) as mail_url:
        store = CredentialStore()
        store.add(Credential(id="agent-password", email="", password="OriginalPass123!"))
        store.add(Credential(id="agent-new-password", email="", password="NewPassword456!"))

        events = []

        def emitter(etype, payload):
            events.append((etype, payload))

        executor = AgentExecutor(
            execution_id=uuid.uuid4(),
            reasoner=AgentReasoner(provider=None),
            email_provider=HTTPPollMailboxProvider(base_url=mail_url),
            credential_store=store,
            event_emitter=emitter,
        )

        async with BrowserSession() as browser:
            outcome = await executor.run(
                browser,
                objective=(
                    "Test the forgot password functionality. If the account does not exist, "
                    "create one using a temporary email address, log out, then use that same "
                    "email address to test the forgot password flow."
                ),
                target_url=f"{app_url}/?v=a",
            )

        print("\n=== EVENTS ===")
        for etype, payload in events:
            detail = {k: (str(v)[:70]) for k, v in payload.items()}
            print(f"  {etype}: {detail}")
        print("\n=== OUTCOME ===")
        print(outcome.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
