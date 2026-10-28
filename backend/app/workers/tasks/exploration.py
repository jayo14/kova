"""Celery task for autonomous exploration.

Runs the exploration engine in a background worker, with state persisted
outside process memory (Postgres + Redis). Idempotent: won't re-run terminal
sessions. Enforces exploration budget (wall-clock, pages, actions, model calls).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from celery.exceptions import SoftTimeLimitExceeded
from app.workers.celery_app import celery_app
import app.modules.exploration.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
import app.modules.credentials.models  # noqa: F401

logger = logging.getLogger(__name__)

TASK_HARD_TIMEOUT = 660


@celery_app.task(bind=True, name="run_exploration", max_retries=1, time_limit=TASK_HARD_TIMEOUT)
def run_exploration(
    self,
    session_id: str,
    credential: dict | None = None,
    selected_role: str | None = None,
    create_account: bool = False,
):
    try:
        asyncio.run(
            _run_exploration_async(
                self,
                session_id,
                credential=credential,
                selected_role=selected_role,
                create_account=create_account,
            )
        )
    except SoftTimeLimitExceeded:
        logger.warning("Exploration %s hit soft time limit, graceful shutdown", session_id)


async def _run_exploration_async(
    task,
    session_id: str,
    credential: dict | None = None,
    selected_role: str | None = None,
    create_account: bool = False,
):
    from app.infrastructure.database.session import async_session_factory
    from app.modules.exploration.models import ExplorationStatus
    from app.modules.exploration.repository import (
        ExplorationEventRepository,
        ExplorationRepository,
    )
    from app.engine.exploration.explorer import ExplorationEngine
    from app.config.settings import get_settings
    from app.engine.execution.control import is_cancel_requested

    settings = get_settings()

    async with async_session_factory() as db:
        repo = ExplorationRepository(db)
        event_repo = ExplorationEventRepository(db)

        session_uuid = uuid.UUID(session_id)
        session = await repo.get_by_id(session_uuid)
        if session is None:
            logger.error("Exploration session %s not found", session_id)
            raise ValueError(f"Exploration session {session_id} not found")

        terminal_states = {
            ExplorationStatus.COMPLETED.value,
            ExplorationStatus.FAILED.value,
            ExplorationStatus.CANCELLED.value,
            ExplorationStatus.BLOCKED.value,
        }
        if session.status in terminal_states:
            logger.info(
                "Exploration %s already in terminal state %s, skipping",
                session_id,
                session.status,
            )
            return {"status": "skipped", "reason": "already_terminal"}

        if session.status not in (ExplorationStatus.CREATED.value,):
            logger.info(
                "Exploration %s is already claimed in %s", session_id, session.status
            )
            return {"status": "skipped", "reason": "already_claimed"}

        await repo.update_status(session_uuid, ExplorationStatus.CONNECTING)
        await db.commit()

        event_count = 0
        emit_lock = asyncio.Lock()

        async def event_emitter(event_type: str, payload: dict):
            nonlocal event_count
            async with emit_lock:
                try:
                    from app.modules.executions.reporting import sanitize_payload
                    sanitized_payload = sanitize_payload(payload) or {}
                    await event_repo.create(
                        exploration_id=session_uuid,
                        event_type=event_type,
                        payload=sanitized_payload,
                    )
                    event_count += 1
                    await db.commit()

                    if event_type == "state_change" and isinstance(payload, dict):
                        status_val = payload.get("status")
                        if status_val:
                            try:
                                status_enum = ExplorationStatus(status_val)
                                await repo.update_status(
                                    session_id=session_uuid,
                                    status=status_enum,
                                )
                                await db.commit()
                            except ValueError:
                                logger.warning("Unknown exploration status: %s", status_val)
                    elif event_type == "missions" and isinstance(payload, dict):
                        raw_missions = payload.get("missions")
                        if raw_missions is not None:
                            try:
                                await repo.update_status(
                                    session_id=session_uuid,
                                    candidate_missions=raw_missions,
                                )
                                await db.commit()
                            except Exception as e:
                                logger.warning("Failed to persist candidate missions: %s", e)
                    elif event_type == "discovery" and isinstance(payload, dict):
                        raw_discoveries = payload.get("discoveries")
                        if raw_discoveries is not None:
                            try:
                                await repo.update_status(
                                    session_id=session_uuid,
                                    discoveries=raw_discoveries,
                                )
                                await db.commit()
                            except Exception as e:
                                logger.warning("Failed to persist discoveries: %s", e)
                    elif event_type == "question" and isinstance(payload, dict):
                        raw_q = payload.get("question")
                        if raw_q is not None:
                            try:
                                await repo.update_status(
                                    session_id=session_uuid,
                                    question=raw_q,
                                )
                                await db.commit()
                            except Exception as e:
                                logger.warning("Failed to persist question: %s", e)
                    elif event_type == "auth.required" and isinstance(payload, dict):
                        raw_auth = payload.get("request") or payload
                        try:
                            await repo.update_status(
                                session_id=session_uuid,
                                credential_request=raw_auth,
                            )
                            await db.commit()
                        except Exception as e:
                            logger.warning("Failed to persist credential request: %s", e)
                    elif event_type == "budget.exceeded" and isinstance(payload, dict):
                        try:
                            await repo.update_status(
                                session_id=session_uuid,
                                budget_used=payload.get("budget_used"),
                                budget_cutoff=datetime.now(timezone.utc),
                            )
                            await db.commit()
                        except Exception as e:
                            logger.warning("Failed to persist budget cutoff: %s", e)
                except Exception as ex:
                    logger.warning("Failed to record event %s: %s", event_type, ex)
                    try:
                        await db.rollback()
                    except Exception:
                        pass

        engine = ExplorationEngine(
            exploration_id=session_uuid,
            url=session.url,
            goal=session.goal,
            event_emitter=event_emitter,
            credential_id=None,
            project_id=session.project_id,
            db_session=db,
        )

        try:
            # Run agentic exploration loop if possible
            try:
                if not engine._browser:
                    from app.engine.browser.session import BrowserSession
                    engine._browser = BrowserSession()
                if not getattr(engine._browser, 'is_started', False):
                    await engine._browser.start()
                page = engine._browser.page
                from app.engine.exploration.agent import ExplorationAgent
                agent = ExplorationAgent(engine, page, event_emitter=event_emitter)
                agent_result = await agent.run(max_steps=50)
                await event_emitter("exploration.agent.summary", agent_result)
            except Exception as agent_err:
                logger.debug("Agent exploration skipped/failed: %s", agent_err)

            if await is_cancel_requested(session_id):
                current = await repo.get_by_id(session_uuid)
                if current and current.status not in terminal_states:
                    await repo.update_status(session_uuid, ExplorationStatus.CANCELLED)
                await db.commit()
                logger.info("Exploration %s cancelled before start", session_id)
                return {"status": "cancelled", "session_id": session_id}

            result = await asyncio.wait_for(
                engine.explore(
                    credential=credential,
                    selected_role=selected_role,
                    create_account=create_account,
                ),
                timeout=settings.EXPLORATION_MAX_WALL_CLOCK_SECONDS,
            )

            try:
                await asyncio.wait_for(engine.drain_background(), timeout=5.0)
            except Exception:
                pass

            await db.flush()

            status = result.get("status", ExplorationStatus.READY)
            await repo.update_status(
                session_id=session_uuid,
                status=status,
                error_message=result.get("error_message"),
                discoveries=result.get("discoveries"),
                candidate_missions=result.get("candidate_missions"),
                question=result.get("question"),
                credential_request=result.get("credential_request"),
                selected_role=result.get("selected_role") or selected_role,
                goal=result.get("goal") or session.goal,
                budget_used=result.get("budget_used"),
                clear_credential_request=(
                    result.get("credential_request") is None
                    and status != ExplorationStatus.AUTH_REQUIRED
                ),
                clear_question=(
                    result.get("question") is None
                    and status != ExplorationStatus.ASKING
                ),
            )

            if status == ExplorationStatus.READY and session.project_id:
                try:
                    disc_data = result.get("discovery_result")
                    if disc_data:
                        from app.modules.product_graph.schemas import DiscoveryResult
                        from app.modules.product_graph.service import ProductGraphService
                        disc_obj = DiscoveryResult.model_validate(disc_data)
                        pg_service = ProductGraphService(db)
                        await pg_service.upsert_from_discovery(session.project_id, disc_obj)
                        await event_emitter("product_graph.updated", {"project_id": str(session.project_id)})
                except Exception as pg_e:
                    logger.warning("Could not persist discovery to Product Graph: %s", pg_e)

                brand_data = result.get("brand_metadata")
                if brand_data:
                    try:
                        from app.modules.projects.repository import ProjectRepository
                        proj_repo = ProjectRepository(db)
                        proj = await proj_repo.get_by_id(session.project_id)
                        if proj:
                            final_env = dict(proj.env_config or {})
                            if brand_data.get("logo_url"):
                                final_env["logo_url"] = brand_data["logo_url"]
                            if brand_data.get("favicon_url"):
                                final_env["favicon_url"] = brand_data["favicon_url"]
                            proj.env_config = final_env
                    except Exception as b_err:
                        logger.debug("Could not save final brand metadata: %s", b_err)

            await db.commit()
            return {"status": status.lower() if isinstance(status, str) else getattr(status, "value", str(status)), "session_id": session_id}

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
            error_msg = f"Exploration timed out after {settings.EXPLORATION_MAX_WALL_CLOCK_SECONDS}s"
            logger.warning("Exploration %s timed out", session_id)
            engine.cancel_background()
            try:
                if engine._browser:
                    await asyncio.shield(engine._browser.close())
            except Exception:
                pass
            try:
                async with async_session_factory() as fail_db:
                    fail_repo = ExplorationRepository(fail_db)
                    fail_event_repo = ExplorationEventRepository(fail_db)
                    await fail_event_repo.create(
                        exploration_id=session_uuid,
                        event_type="exploration.failed",
                        payload={"error": error_msg, "reason": "timeout"},
                    )
                    await fail_repo.update_status(
                        session_id=session_uuid,
                        status=ExplorationStatus.FAILED,
                        error_message=error_msg,
                    )
                    await fail_db.commit()
            except Exception as ex:
                logger.error("Failed to mark exploration %s FAILED: %s", session_id, ex)
            return {"status": "failed", "session_id": session_id, "reason": "timeout"}

        except Exception as e:
            logger.exception("Exploration flow failed for session %s: %s", session_id)
            engine.cancel_background()
            try:
                if engine._browser:
                    await asyncio.shield(engine._browser.close())
            except Exception:
                pass
            try:
                async with async_session_factory() as fail_db:
                    fail_repo = ExplorationRepository(fail_db)
                    fail_event_repo = ExplorationEventRepository(fail_db)
                    await fail_event_repo.create(
                        exploration_id=session_uuid,
                        event_type="exploration.failed",
                        payload={"error": str(e)},
                    )
                    await fail_repo.update_status(
                        session_id=session_uuid,
                        status=ExplorationStatus.FAILED,
                        error_message=str(e),
                    )
                    await fail_db.commit()
            except Exception:
                logger.exception("Failed to persist exploration failure for %s", session_id)
            raise
        finally:
            try:
                if engine._browser and getattr(engine._browser, "is_started", False):
                    await engine._browser.close()
            except Exception:
                pass
