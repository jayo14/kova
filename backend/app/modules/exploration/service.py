from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.exploration.explorer import ExplorationEngine
from app.engine.browser.session import BrowserSession
from app.modules.credentials.schemas import CredentialCreate
from app.modules.credentials.service import CredentialService
from app.modules.exploration.models import (
    ExplorationEvent,
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
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate

logger = logging.getLogger(__name__)

# Maximum time an exploration can run before being forcibly timed out
EXPLORATION_TIMEOUT_SECONDS = 120

# Active browser sessions keyed by exploration session ID
_active_browser_sessions: dict[uuid.UUID, BrowserSession] = {}

# Active exploration asyncio tasks keyed by exploration session ID
_active_exploration_tasks: dict[uuid.UUID, asyncio.Task] = {}


def _register_exploration_task(session_id: uuid.UUID, coro) -> asyncio.Task:
    """Create and track an exploration background task."""
    # Cancel any previous task for this session (e.g. before re-auth)
    old_task = _active_exploration_tasks.pop(session_id, None)
    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(coro)
    _active_exploration_tasks[session_id] = task
    task.add_done_callback(lambda t: _active_exploration_tasks.pop(session_id, None) if _active_exploration_tasks.get(session_id) is t else None)
    return task


def extract_project_name(hostname: str) -> str:
    """Extract a human-friendly project/brand name from a hostname or URL.

    Handles www, generic infrastructure subdomains, kebab/snake case, and known brands.
    """
    clean_host = (hostname or "").lower().strip()
    if "://" in clean_host:
        clean_host = urlparse(clean_host).hostname or clean_host
    if ":" in clean_host:
        clean_host = clean_host.split(":")[0]

    # Strip leading www.
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

    if brand_part.lower() == "summastudy":
        return "SummaStudy"

    # Handle kebab-case or snake_case: "my-study-tool" -> "My Study Tool"
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

    async def create_and_start_exploration(
        self,
        data: ExplorationCreate,
        user_id: uuid.UUID,
    ) -> ExplorationSession:
        """Finds or creates a project for the target URL, creates session, and begins background exploration."""
        target_url = data.url.strip()
        parsed = urlparse(target_url)
        hostname = parsed.hostname or target_url

        # 1. Deduplicate/find project for user by domain / base_url (normalized without www)
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

            matched_project = await self.project_repo.create(
                user_id=user_id,
                name=project_name,
                base_url=base_url,
                description=f"Automated project for {base_url}",
            )

        # 2. Create exploration session
        session = await self.repo.create(
            user_id=user_id,
            url=target_url,
            goal=data.goal,
            project_id=matched_project.id,
        )
        await self.db.commit()

        # 3. Launch exploration in background task
        _register_exploration_task(
            session.id,
            self._execute_exploration_flow(
                session_id=session.id,
                user_id=user_id,
                url=target_url,
                goal=data.goal,
            ),
        )

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

        # Optionally save credential for the project
        if data.save and session.project_id:
            try:
                cred_service = CredentialService(self.db)
                cred_name = f"explore-cred-{uuid.uuid4().hex[:6]}"
                await cred_service.create_credential(
                    project_id=session.project_id,
                    user_id=user_id,
                    data=CredentialCreate(
                        name=cred_name,
                        email=data.email,
                        password=data.password,
                    ),
                )
            except Exception as e:
                logger.warning("Could not save credential to project: %s", e)

        # Transition status to AUTHENTICATING
        await self.repo.update_status(
            session_id=session_id,
            status=ExplorationStatus.AUTHENTICATING,
        )
        await self.db.commit()

        # Run authenticated exploration in background
        _register_exploration_task(
            session_id,
            self._execute_exploration_flow(
                session_id=session_id,
                user_id=user_id,
                url=session.url,
                goal=session.goal,
                credential={"email": data.email, "password": data.password},
                selected_role=session.selected_role,
            ),
        )

        return session

    async def create_account(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ExplorationCreateAccount,
    ) -> ExplorationSession | None:
        """Attempt to create an account on the target site automatically.

        If email/password are provided, use them; otherwise generate random credentials.
        """
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None

        # Generate credentials if not provided
        import secrets
        import string
        email = data.email
        password = data.password
        if not email:
            random_suffix = secrets.token_hex(4)
            email = f"kova-test-{random_suffix}@example.com"
        if not password:
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for _ in range(16))

        # Save credential for the project
        if session.project_id:
            try:
                cred_service = CredentialService(self.db)
                cred_name = f"auto-created-{uuid.uuid4().hex[:6]}"
                await cred_service.create_credential(
                    project_id=session.project_id,
                    user_id=user_id,
                    data=CredentialCreate(
                        name=cred_name,
                        email=email,
                        password=password,
                    ),
                )
            except Exception as e:
                logger.warning("Could not save created credential to project: %s", e)

        # Transition status to AUTHENTICATING
        await self.repo.update_status(
            session_id=session_id,
            status=ExplorationStatus.AUTHENTICATING,
        )
        await self.db.commit()

        # Run account creation exploration in background
        _register_exploration_task(
            session_id,
            self._execute_exploration_flow(
                session_id=session_id,
                user_id=user_id,
                url=session.url,
                goal=session.goal,
                credential={"email": email, "password": password},
                selected_role=session.selected_role,
                create_account=True,
            ),
        )

        return session

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

        # Transition status to DISCOVERING
        await self.repo.update_status(
            session_id=session_id,
            status=ExplorationStatus.DISCOVERING,
            selected_role=role_selected,
        )
        await self.db.commit()

        # Continue exploration with selected role
        _register_exploration_task(
            session_id,
            self._execute_exploration_flow(
                session_id=session_id,
                user_id=user_id,
                url=session.url,
                goal=session.goal,
                selected_role=role_selected,
            ),
        )

        return session

    async def cancel_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ExplorationSession | None:
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return None

        # Cancel any active background task
        task = _active_exploration_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

        await self.cleanup_browser_session(session_id)
        await self.repo.update_status(
            session_id=session_id,
            status=ExplorationStatus.CANCELLED,
        )
        await self.event_repo.create(
            exploration_id=session_id,
            event_type="exploration.cancelled",
            payload={"message": "Exploration stopped by user"},
        )
        await self.db.commit()
        return session

    async def navigate_browser(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
    ) -> dict[str, Any]:
        """Navigate the browser (back, forward, or reload) for an active exploration.

        Args:
            session_id: Exploration session ID
            user_id: User ID for authorization
            action: One of 'back', 'forward', 'reload'

        Returns:
            dict with url, path, title, or error
        """
        session = await self.repo.get_by_id_and_user(session_id, user_id)
        if not session:
            return {"error": "Session not found"}

        browser = _active_browser_sessions.get(session_id)
        if not browser or not browser.page:
            return {"error": "No active browser session. Exploration may have finished."}

        page = browser.page

        from app.infrastructure.database.session import async_session_factory

        try:
            if action == "back":
                await page.go_back(wait_until="domcontentloaded")
            elif action == "forward":
                await page.go_forward(wait_until="domcontentloaded")
            elif action == "reload":
                await page.reload(wait_until="domcontentloaded")
            else:
                return {"error": f"Unknown navigation action: {action}"}

            # Wait for page to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # Emit URL change event
            current_url = page.url
            async with async_session_factory() as event_db:
                event_repo = ExplorationEventRepository(event_db)
                await event_repo.create(
                    exploration_id=session_id,
                    event_type="page.url_changed",
                    payload={
                        "url": current_url,
                        "path": urlparse(current_url).path,
                    },
                )
                await event_db.commit()

            # Capture screenshot
            from app.engine.browser.screenshot_storage import ScreenshotStorage
            storage = ScreenshotStorage()
            screenshot_bytes = await page.screenshot()
            storage_meta = await asyncio.to_thread(
                storage.save, str(session_id), screenshot_bytes, current_url
            )

            async with async_session_factory() as event_db:
                event_repo = ExplorationEventRepository(event_db)
                screenshot_event = {"url": current_url}
                if storage_meta.get("screenshot_url"):
                    screenshot_event["screenshot_url"] = storage_meta["screenshot_url"]
                elif storage_meta.get("screenshot_key"):
                    screenshot_event["screenshot_key"] = storage_meta["screenshot_key"]
                await event_repo.create(
                    exploration_id=session_id,
                    event_type="browser.screenshot",
                    payload=screenshot_event,
                )
                await event_db.commit()

            return {
                "url": current_url,
                "path": urlparse(current_url).path,
                "title": await page.title(),
            }

        except Exception as e:
            logger.warning("Browser navigation failed for session %s: %s", session_id, e)
            return {"error": str(e)}

    async def cleanup_browser_session(self, session_id: uuid.UUID):
        """Close and remove an active browser session."""
        browser = _active_browser_sessions.pop(session_id, None)
        if browser:
            try:
                await browser.close()
            except Exception as e:
                logger.warning("Failed to close browser session %s: %s", session_id, e)

    async def _execute_exploration_flow(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        url: str,
        goal: str | None = None,
        credential: dict | None = None,
        selected_role: str | None = None,
        create_account: bool = False,
    ):
        """Runs the exploration engine with an isolated DB session."""
        from app.infrastructure.database.session import async_session_factory

        async def _mark_failed_fresh(error_msg: str, reason: str | None = None) -> None:
            """Write FAILED status on a fresh DB session (shared session may be stuck)."""
            try:
                async with async_session_factory() as fail_db:
                    fail_event_repo = ExplorationEventRepository(fail_db)
                    fail_repo = ExplorationRepository(fail_db)
                    payload = {"error": error_msg}
                    if reason:
                        payload["reason"] = reason
                    await fail_event_repo.create(
                        exploration_id=session_id,
                        event_type="exploration.failed",
                        payload=payload,
                    )
                    await fail_repo.update_status(
                        session_id=session_id,
                        status=ExplorationStatus.FAILED,
                        error_message=error_msg,
                    )
                    await fail_db.commit()
            except Exception as ex:
                logger.error("Failed to mark exploration %s FAILED: %s", session_id, ex)

        async with async_session_factory() as db:
            repo = ExplorationRepository(db)
            event_repo = ExplorationEventRepository(db)

            event_count = 0
            emit_lock = asyncio.Lock()

            async def event_emitter(event_type: str, payload: dict):
                nonlocal event_count
                async with emit_lock:
                    try:
                        await event_repo.create(
                            exploration_id=session_id,
                            event_type=event_type,
                            payload=payload,
                        )
                        event_count += 1
                        # Commit immediately so SSE polling (separate DB session) can see events
                        await db.commit()

                        # Keep session status and data in sync so SSE polling and
                        # frontend 3s safety-net poll see state changes live
                        if event_type == "state_change" and isinstance(payload, dict):
                            status_val = payload.get("status")
                            if status_val:
                                try:
                                    status_enum = ExplorationStatus(status_val)
                                    await repo.update_status(
                                        session_id=session_id,
                                        status=status_enum,
                                    )
                                    await db.commit()
                                except ValueError:
                                    logger.warning("Unknown exploration status: %s", status_val)
                                except Exception as e:
                                    logger.warning("Failed to update session status to %s: %s", status_val, e)
                        elif event_type == "missions" and isinstance(payload, dict):
                            raw_missions = payload.get("missions")
                            if raw_missions is not None:
                                try:
                                    await repo.update_status(
                                        session_id=session_id,
                                        candidate_missions=raw_missions,
                                    )
                                    await db.commit()
                                except Exception as e:
                                    logger.warning("Failed to persist candidate missions for session %s: %s", session_id, e)
                        elif event_type == "discovery" and isinstance(payload, dict):
                            raw_discoveries = payload.get("discoveries")
                            if raw_discoveries is not None:
                                try:
                                    await repo.update_status(
                                        session_id=session_id,
                                        discoveries=raw_discoveries,
                                    )
                                    await db.commit()
                                except Exception as e:
                                    logger.warning("Failed to persist discoveries for session %s: %s", session_id, e)
                        elif event_type == "question" and isinstance(payload, dict):
                            raw_q = payload.get("question")
                            if raw_q is not None:
                                try:
                                    await repo.update_status(
                                        session_id=session_id,
                                        question=raw_q,
                                    )
                                    await db.commit()
                                except Exception as e:
                                    logger.warning("Failed to persist question for session %s: %s", session_id, e)
                        elif event_type == "auth.required" and isinstance(payload, dict):
                            raw_auth = payload.get("request") or payload
                            try:
                                await repo.update_status(
                                    session_id=session_id,
                                    credential_request=raw_auth,
                                )
                                await db.commit()
                            except Exception as e:
                                logger.warning("Failed to persist credential request for session %s: %s", session_id, e)
                    except Exception as ex:
                        logger.warning("Failed to record event %s: %s", event_type, ex)

            existing_browser = _active_browser_sessions.get(session_id)

            # Resolve a project credential so generated auth journeys can
            # reference it by id instead of embedding secrets in steps.
            credential_id: str | None = None
            if session.project_id:
                try:
                    from app.modules.credentials.repository import CredentialRepository
                    cred_repo = CredentialRepository(db)
                    project_creds = await cred_repo.list_by_project(session.project_id, limit=1)
                    if project_creds:
                        credential_id = project_creds[0].name
                except Exception as e:
                    logger.debug("Could not resolve project credential for exploration: %s", e)

            engine = ExplorationEngine(
                exploration_id=session_id,
                url=url,
                goal=goal,
                event_emitter=event_emitter,
                existing_browser=existing_browser,
                credential_id=credential_id,
            )

            try:
                # Run exploration with timeout
                result = await asyncio.wait_for(
                    engine.explore(
                        credential=credential,
                        selected_role=selected_role,
                        create_account=create_account,
                    ),
                    timeout=EXPLORATION_TIMEOUT_SECONDS,
                )

                # Wait for background screenshot tasks before touching shared session
                try:
                    await asyncio.wait_for(engine.drain_background(), timeout=5.0)
                except Exception:
                    pass

                # Store browser session for navigation if exploration succeeded or needs input
                if engine._browser and result.get("status") in (
                    ExplorationStatus.READY,
                    ExplorationStatus.AUTH_REQUIRED,
                    ExplorationStatus.ASKING,
                ):
                    _active_browser_sessions[session_id] = engine._browser
                elif result.get("status") in (ExplorationStatus.FAILED, ExplorationStatus.CANCELLED):
                    await self.cleanup_browser_session(session_id)

                # Flush remaining events before final status update
                await db.flush()

                status = result.get("status", ExplorationStatus.READY)
                # Engine already emitted state_change for terminal states;
                # just persist the final session data
                await repo.update_status(
                    session_id=session_id,
                    status=status,
                    error_message=result.get("error_message"),
                    discoveries=result.get("discoveries"),
                    candidate_missions=result.get("candidate_missions"),
                    question=result.get("question"),
                    credential_request=result.get("credential_request"),
                    selected_role=selected_role,
                )
                await db.commit()

            except asyncio.CancelledError:
                logger.info("Exploration flow cancelled for session %s", session_id)
                engine.cancel_background()
                try:
                    if engine._browser:
                        await asyncio.shield(engine._browser.close())
                except Exception:
                    pass
                raise

            except asyncio.TimeoutError:
                error_msg = f"Exploration timed out after {EXPLORATION_TIMEOUT_SECONDS}s"
                logger.warning("Exploration %s timed out", session_id)
                engine.cancel_background()
                try:
                    if engine._browser:
                        await asyncio.shield(engine._browser.close())
                except Exception:
                    pass
                await _mark_failed_fresh(error_msg, reason="timeout")

            except Exception as e:
                logger.exception("Exploration flow failed for session %s: %s", session_id, e)
                engine.cancel_background()
                try:
                    if engine._browser:
                        await asyncio.shield(engine._browser.close())
                except Exception:
                    pass
                await _mark_failed_fresh(str(e))
