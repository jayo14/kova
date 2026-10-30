from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credentials.schemas import CredentialCreate
from app.modules.credentials.service import CredentialService
from app.modules.exploration.models import (
    ExplorationSession,
    ExplorationStatus,
)
from app.modules.exploration.repository import (
    ExplorationEventRepository,
    ExplorationRepository,
)
from app.modules.exploration.schemas import (
    ExplorationCreate,
    ExplorationCreateAccount,
    ExplorationCredentialSubmit,
    ExplorationAnswerSubmit,
)
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate
from app.engine.execution.control import request_cancel, publish_command
from app.engine.execution.control import queue_worker_input
from app.engine.execution.control import publish_worker_command

logger = logging.getLogger(__name__)


def extract_project_name(hostname: str) -> str:
    """Extract a human-friendly project/brand name from a hostname or URL.

    Handles www, generic infrastructure subdomains, kebab/snake case, and known brands.
    """
    clean_host = (hostname or "").lower().strip()
    if "://" in clean_host:
        clean_host = urlparse(clean_host).hostname or clean_host
    if ":" in clean_host:
        clean_host = clean_host.split(":")[0]

    clean_host = re.sub(r"^www\d*\.", "", clean_host)

    if not clean_host:
        return "Project"
    if clean_host in ("localhost", "127.0.0.1"):
        return "Localhost"

    parts = clean_host.split(".")
    generic_subdomains = {
        "app", "web", "staging", "dev", "api", "auth", "admin", "beta", "m", "portal", "dashboard", "preview"
    }
    while len(parts) > 2 and parts[0] in generic_subdomains:
        parts.pop(0)

    brand_part = parts[0] if parts else "Project"


    words = [w for w in re.split(r"[-_]", brand_part) if w]
    if len(words) > 1:
        return " ".join(w.capitalize() for w in words)

    return brand_part.capitalize()


class ExplorationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExplorationRepository(db)
        self.event_repo = ExplorationEventRepository(db)
        self.project_repo = ProjectRepository(db)

    async def _enqueue_exploration(
        self,
        session_id: uuid.UUID,
    ) -> None:
        """Enqueue the exploration session on the Celery worker.

        Routes to the plan-appropriate queue (kova-free / kova-pro /
        kova-enterprise) based on the session's project organization plan.
        Falls back to kova-free if the plan cannot be resolved.
        """
        from app.workers.tasks.exploration import run_exploration
        from app.workers.celery_app import get_queue_for_plan

        queue = "kova-free"
        session = await self.repo.get_by_id(session_id)
        if session and session.project_id:
            project = await self.project_repo.get_by_id(session.project_id)
            if project and project.org_id:
                from app.modules.organizations.repository import OrganizationRepository

                org_repo = OrganizationRepository(self.db)
                org = await org_repo.get_by_id(project.org_id)
                if org:
                    queue = get_queue_for_plan(org.plan)

        await asyncio.to_thread(
            run_exploration.apply_async,
            args=[str(session_id)],
            queue=queue,
        )
        logger.info("Enqueued exploration %s to Celery queue %s", session_id, queue)

    async def create_and_start_exploration(
        self,
        data: ExplorationCreate,
        user_id: uuid.UUID,
    ) -> ExplorationSession:
        """Finds or creates a project for the target URL, creates session, and enqueues exploration."""
        target_url = data.url.strip()
        parsed = urlparse(target_url)
        hostname = parsed.hostname or target_url

        projects = await self.project_repo.list_by_user(user_id, limit=100)
        matched_project = None
        current_norm_host = re.sub(r"^www\d*\.", "", (hostname or "").lower())

        for p in projects:
            try:
                p_host = re.sub(r"^www\d*\.", "", (urlparse(p.base_url).hostname or "").lower())
                if p_host == current_norm_host:
                    matched_project = p
                    break
            except Exception as e:
                logger.debug("Failed to parse base_url for project %s: %s", p.id, e)

        if not matched_project:
            project_name = extract_project_name(hostname)
            base_url = f"{parsed.scheme or 'https'}://{hostname}"
            clean_host = re.sub(r"^www\d*\.", "", (hostname or "").lower())
            default_favicon = (
                f"https://www.google.com/s2/favicons?domain={clean_host}&sz=128"
                if clean_host
                else None
            )

            matched_project = await self.project_repo.create(
                user_id=user_id,
                name=project_name,
                base_url=base_url,
                description=f"Automated project for {base_url}",
                env_config=(
                    {"logo_url": default_favicon, "favicon_url": default_favicon}
                    if default_favicon
                    else {}
                ),
            )

        session = await self.repo.create(
            user_id=user_id,
            url=target_url,
            goal=data.goal,
            project_id=matched_project.id,
        )
        await self.db.commit()

        await self._enqueue_exploration(session.id)

        return session

    async def get_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ExplorationSession | None:
        return await self.repo.get_by_id_and_user(session_id, user_id)

    async def submit_credentials(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ExplorationCredentialSubmit,
    ) -> ExplorationSession | None:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None

        email = data.email
        password = data.password

        if data.credential_id:
            from app.modules.credentials.repository import CredentialRepository
            from app.modules.credentials.crypto import decrypt_credential

            cred_repo = CredentialRepository(self.db)
            cred = await cred_repo.get_by_id(data.credential_id)
            if not cred:
                raise ValueError("Selected credential not found.")

            project = await self.project_repo.get_by_id_and_user(cred.project_id, user_id)
            if not project:
                raise ValueError("Unauthorized access to credential.")

            email = cred.email
            raw_pass = cred.password
            if not raw_pass:
                raise ValueError("Stored credential password is empty.")
            try:
                password = decrypt_credential(raw_pass)
            except Exception as ex:
                logger.error("Failed to decrypt stored credential")
                raise ValueError(
                    "Failed to decrypt stored credential; stored value is corrupt or invalid."
                ) from ex

        if not email or not password:
            raise ValueError("Email and password are required.")

        if data.save and session.project_id and not data.credential_id:
            try:
                cred_service = CredentialService(self.db)
                cred_name = f"explore-cred-{uuid.uuid4().hex[:6]}"
                await cred_service.create_credential(
                    project_id=session.project_id,
                    data=CredentialCreate(name=cred_name, email=email, password=password),
                )
            except Exception:
                logger.warning("Could not save credential to project")

        # Keep secrets out of broker task arguments and persist the resume
        # signal in the shared control queue consumed by the worker.
        await queue_worker_input(
            str(session_id),
            {"kind": "credentials", "email": email, "password": password},
        )
        updated_session = await self.repo.update_status(
            session_id=session_id,
            status=ExplorationStatus.AUTHENTICATING,
            clear_credential_request=True,
        )
        await self.db.commit()
        await self._enqueue_exploration(session_id)

        return updated_session or session

    async def create_account(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ExplorationCreateAccount,
    ) -> ExplorationSession | None:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None

        import secrets

        email = data.email
        password = data.password
        if not email:
            random_suffix = secrets.token_hex(4)
            email = f"kova-tester-{random_suffix}@example.com"
        if not password:
            random_suffix = secrets.token_hex(4)
            password = f"KovaPass!{random_suffix}"

        if session.project_id:
            try:
                cred_service = CredentialService(self.db)
                cred_name = f"auto-created-{uuid.uuid4().hex[:6]}"
                await cred_service.create_credential(
                    project_id=session.project_id,
                    data=CredentialCreate(name=cred_name, email=email, password=password),
                )
            except Exception:
                logger.warning("Could not save created credential to project")

        await queue_worker_input(
            str(session_id),
            {
                "kind": "credentials",
                "email": email,
                "password": password,
                "create_account": True,
            },
        )
        updated_session = await self.repo.update_status(
            session_id=session_id,
            status=ExplorationStatus.AUTHENTICATING,
            clear_credential_request=True,
        )
        await self.db.commit()
        await self._enqueue_exploration(session_id)

        return updated_session or session

    async def submit_answer(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ExplorationAnswerSubmit,
    ) -> ExplorationSession | None:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None

        role_selected = data.answer

        await queue_worker_input(
            str(session_id), {"kind": "answer", "selected_role": role_selected}
        )
        updated_session = await self.repo.update_status(
            session_id=session_id,
            status=ExplorationStatus.DISCOVERING,
            selected_role=role_selected,
            clear_question=True,
        )
        await self.db.commit()

        await self._enqueue_exploration(session_id)

        return updated_session or session

    async def cancel_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ExplorationSession | None:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None

        await request_cancel(str(session_id), reason="User requested cancellation")

        await self.repo.update_status(session_id=session_id, status=ExplorationStatus.CANCELLED)
        await self.event_repo.create(
            exploration_id=session_id,
            event_type="exploration.cancelled",
            payload={"message": "Exploration stopped by user"},
        )
        await self.db.commit()
        return session

    async def pause_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExplorationSession | None:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None
        if session.status in {
            ExplorationStatus.READY.value,
            ExplorationStatus.AUTH_REQUIRED.value,
            ExplorationStatus.ASKING.value,
        }:
            return session
        await self.repo.update_status(session_id, ExplorationStatus.PAUSED)
        await self.db.commit()
        await publish_command(str(session_id), "pause")
        return await self.repo.get_by_id(session_id)

    async def resume_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExplorationSession | None:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None
        if session.status != ExplorationStatus.PAUSED.value:
            raise ValueError("Only paused explorations can be resumed.")
        await queue_worker_input(str(session_id), {"kind": "resume"})
        updated = await self.repo.update_status(
            session_id,
            ExplorationStatus.DISCOVERING,
            clear_question=True,
            clear_credential_request=True,
        )
        await self.db.commit()
        await self._enqueue_exploration(session_id)
        return updated

    async def navigate_browser(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
    ) -> dict[str, Any]:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return {"error": "Session not found"}

        terminal_states = {
            ExplorationStatus.COMPLETED.value,
            ExplorationStatus.FAILED.value,
            ExplorationStatus.CANCELLED.value,
            ExplorationStatus.READY.value,
            ExplorationStatus.AUTH_REQUIRED.value,
            ExplorationStatus.ASKING.value,
        }
        if session.status in terminal_states:
            return {"error": "No active browser session. Exploration has finished."}

        await publish_worker_command(str(session_id), "navigate", action=action)
        return {"action": action, "status": "queued", "session_id": str(session_id)}

    async def cleanup_browser_session(self, session_id: uuid.UUID):
        from app.engine.execution.control import cleanup_control

        await cleanup_control(str(session_id))
