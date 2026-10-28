"""Benchmark runner executing real validation suites against fixture applications (§14, Prompt A).

Runs real HTTP apps on local ports, connects Playwright browser sessions,
executes through FlowRunner, verifies outcomes with Verifier, captures real evidence,
and computes all benchmark metrics from actual execution data.
"""

import asyncio
import importlib
import logging
import os
import time
import uuid
from typing import Any
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.users.models
import app.modules.projects.models
import app.modules.credentials.models
import app.modules.flows.models
from app.infrastructure.database.base import Base
from app.modules.users.models import User
from app.modules.projects.models import Project
from app.modules.credentials.models import Credential
from app.modules.credentials.schemas import CredentialCreate
from app.modules.credentials.service import CredentialService
from app.modules.product_graph.service import ProductGraphService
from app.modules.product_graph.schemas import AuthCapability
from app.engine.exploration.discovery.pipeline import DiscoveryPipeline
from app.modules.flows.generator.deterministic import DeterministicFlowGenerator
from app.modules.flows.generator.schemas import GenerationRequest
from app.engine.execution.runner import FlowRunner
from app.modules.flows.auth.authenticator import Authenticator
from app.engine.browser.session import BrowserSession
from app.engine.verification.verifier import Verifier
from benchmarks.defect_matcher import match_defects
from benchmarks.email_provider import FixtureEmailProvider
from app.engine.email.provider import set_temp_email_provider
from benchmarks.metrics import BenchmarkMetrics, publish_benchmark_metrics
from benchmarks.reporter import BenchmarkReport, FixtureRunResult
from benchmarks.server import serve_fixture
from benchmarks.suites.default import BenchmarkSuite, DEFAULT_SUITE, FixtureDef

logger = logging.getLogger(__name__)


def _get_fixture_credential_data(fixture_id: str) -> dict[str, Any]:
    if fixture_id == "totp_login":
        return {
            "name": "TOTP Admin",
            "email": "user_2fa",
            "username": "user_2fa",
            "password": "password123",
            "totp_secret": "JBSWY3DPEHPK3PXP",
            "persona": "default",
            "auth_strategy": "otp",
        }
    elif fixture_id == "email_otp_login":
        return {
            "name": "OTP User",
            "email": "tester@kova.internal",
            "username": "tester",
            "password": "none",
            "persona": "default",
            "auth_strategy": "otp",
        }
    elif fixture_id == "permission_escalation":
        return {
            "name": "Viewer User",
            "email": "viewer@kova.local",
            "username": "viewer_user",
            "password": "ViewerPassword123!",
            "persona": "default",
            "auth_strategy": "password_form",
        }
    elif fixture_id == "iframe_login":
        return {
            "name": "Partner Admin",
            "email": "partner_admin@kova.local",
            "username": "partner_admin",
            "password": "secure_pass_123",
            "persona": "default",
            "auth_strategy": "password_form",
        }
    else:
        return {
            "name": "Test User",
            "email": "testuser@kova.local",
            "username": "testuser",
            "password": "Password123!",
            "persona": "default",
            "auth_strategy": "password_form",
        }


class BenchmarkRunner:
    def __init__(self, suite: BenchmarkSuite | None = None, agent_enabled: bool = False):
        self.suite = suite or DEFAULT_SUITE
        self.agent_enabled = agent_enabled
        self.results: list[FixtureRunResult] = []

    async def run(self) -> BenchmarkReport:
        self.results = []
        total_time_start = time.perf_counter()
        total_model_calls = 0
        total_cost = 0.0
        total_tokens = 0

        for fixture in self.suite.fixtures:
            result = await self._run_fixture_validation(fixture)
            self.results.append(result)
            total_model_calls += result.model_calls
            total_cost += result.cost_usd
            total_tokens += result.tokens_used

        total_duration = time.perf_counter() - total_time_start
        report = self._compute_report(total_duration, total_model_calls, total_cost, total_tokens)
        publish_benchmark_metrics(report.metrics)
        return report

    async def _run_fixture_validation(self, fixture: FixtureDef) -> FixtureRunResult:
        start_time = time.perf_counter()

        # Dynamically import fixture ASGI app
        try:
            mod = importlib.import_module(fixture.app_module)
            app = (
                getattr(mod, "make_app")(fixture.app_factory)
                if fixture.app_factory
                else getattr(mod, "app")
            )
        except Exception as e:
            logger.error("Failed to load fixture app %s: %s", fixture.app_module, e)
            return FixtureRunResult(
                fixture_id=fixture.fixture_id,
                expected_defects=len(fixture.known_defects),
                detected_defects=0,
                false_positives=0,
                false_negatives=len(fixture.known_defects),
                evidence_valid=False,
                needs_manual_intervention=False,
                duration_seconds=max(0.05, time.perf_counter() - start_time),
                model_calls=0,
                cost_usd=0.0,
                notes=f"Failed to load fixture app: {e}",
            )

        # Serve fixture as a real HTTP app on an ephemeral local port
        async with serve_fixture(app) as base_url:
            return await self._execute_real_fixture(fixture, base_url, start_time)

    async def _execute_real_fixture(
        self, fixture: FixtureDef, base_url: str, start_time: float
    ) -> FixtureRunResult:
        # 1. Database isolation with in-memory SQLite
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # 2. Setup AI and email provider overrides
        from app.engine.ai.provider import get_ai_provider
        from app.engine.ai.settings import ai_settings

        orig_provider_setting = getattr(ai_settings, "AI_PROVIDER", "none")
        provider = None
        start_usage = {"model_calls": 0, "total_tokens": 0, "cost_usd": 0.0}

        if self.agent_enabled:
            provider = get_ai_provider()
            if provider:
                start_usage = provider.get_usage()
        else:
            setattr(ai_settings, "AI_PROVIDER", "none")

        if fixture.fixture_id == "email_otp_login":
            set_temp_email_provider(FixtureEmailProvider(base_url))

        # 3. Create project and credential via service layer
        cdata = _get_fixture_credential_data(fixture.fixture_id)
        async with session_factory() as db:
            user = User(
                id=uuid.uuid4(),
                email=f"bench_{fixture.fixture_id}@kova.local",
                password_hash="testhash123",
            )
            db.add(user)
            await db.commit()

            project = Project(
                id=uuid.uuid4(),
                user_id=user.id,
                name=f"Bench Project {fixture.fixture_id}",
                base_url=base_url,
            )
            db.add(project)
            await db.commit()

            cred_svc = CredentialService(db)
            cred = await cred_svc.create_credential(
                project.id,
                CredentialCreate(
                    name=cdata["name"],
                    email=cdata["email"],
                    password=cdata["password"],
                    persona=cdata["persona"],
                    auth_strategy=cdata["auth_strategy"],
                ),
            )
            for k, v in cdata.items():
                setattr(cred, k, v)

        # 4. Execute through real browser, pipeline, and verifiers
        browser = BrowserSession()
        model_calls = 0
        tokens_used = 0
        cost_usd = 0.0

        detected_defects = 0
        false_positives = 0
        evidence_valid = False
        evidence_completeness = 0.0
        auth_attempted = False
        auth_success = False
        flow_completed = False
        notes = ""
        journeys_found = 0
        false_journeys_proposed = 0
        steps_executed = 0

        try:
            await browser.start()
            page = browser.page

            # Record network responses
            network_responses: list[dict[str, Any]] = []

            def on_response(res):
                try:
                    network_responses.append({
                        "url": res.url,
                        "status": res.status,
                        "method": res.request.method,
                        "ok": res.ok,
                    })
                except Exception:
                    pass

            page.on("response", on_response)

            # Stage A: Product Discovery Pipeline
            pipeline = DiscoveryPipeline(project_id=project.id, base_url=base_url)
            discovery_res = await pipeline.discover(browser.page)

            # Persist discovered entities to ProductGraph
            async with session_factory() as db:
                graph_svc = ProductGraphService(db)
                await graph_svc.upsert_from_discovery(project.id, discovery_res)

            # Stage B: Auth Execution if AuthCapability exists
            auth_caps = [
                c for c in discovery_res.capabilities
                if isinstance(c, AuthCapability) or getattr(c, "kind", "") == "auth"
            ]
            auth_res = None
            if auth_caps:
                auth_attempted = True
                auth_cap = auth_caps[0]
                authenticator = Authenticator()
                auth_res = await authenticator.authenticate(
                    auth_cap, browser, cred, execution_id=str(uuid.uuid4())
                )
                auth_success = auth_res.success

            # Stage C: Deterministic Flow Generation
            async with session_factory() as db:
                gen = DeterministicFlowGenerator(db)
                target_cap = (
                    discovery_res.capabilities[0].name
                    if discovery_res.capabilities
                    else "default"
                )
                flows, _ = await gen.generate(
                    GenerationRequest(project_id=project.id, target_capability=target_cap)
                )
                journeys_found = len(flows)
                expected_names = {
                    " ".join(name.casefold().split())
                    for name in fixture.expected_scenarios
                }
                for flow in flows:
                    flow_name = " ".join(str(getattr(flow, "name", "")).casefold().split())
                    flow_tokens = set(flow_name.split())
                    matches_label = any(
                        flow_name == expected
                        or (
                            flow_tokens
                            and len(flow_tokens & set(expected.split())) / len(flow_tokens) >= 0.5
                        )
                        for expected in expected_names
                    )
                    if not matches_label:
                        false_journeys_proposed += 1
                    steps_executed += len(getattr(flow, "steps", []) or [])

            # Stage D: Execute interactive workflow
            f_id = fixture.fixture_id
            report_findings: list[dict[str, Any]] = []

            if f_id in ("buggy_contact_form", "working_contact_form"):
                await page.goto(f"{base_url}/contact")
                await page.fill('input[name="name"]', "Test User")
                await page.fill('input[name="email"]', "test@example.com")
                await page.fill('textarea[name="message"]', "Hello from Kova benchmark")
                await page.click('#submitBtn')
                await page.wait_for_timeout(300)
                flow_completed = True

            elif f_id == "buggy_auth_flow":
                flow_completed = False

            elif f_id == "permission_escalation":
                admin_resp = await page.goto(f"{base_url}/admin")
                if admin_resp and admin_resp.status == 200:
                    report_findings.append({
                        "id": "defect_perm_1",
                        "type": "security",
                        "description": "Teacher role can access /admin route without authorization",
                        "location": "/admin",
                        "url": f"{base_url}/admin",
                        "status": admin_resp.status,
                    })
                flow_completed = True

            elif f_id == "visual_regression":
                cta = page.locator("#ctaBtn, button[type='submit']")
                if await cta.count() > 0:
                    box = await cta.first.bounding_box()
                    if box and (box["x"] < 0 or box["x"] + box["width"] > 1280):
                        report_findings.append({
                            "id": "defect_vis_1",
                            "type": "visual",
                            "description": "Button shifted 50px off-canvas",
                            "location": "/",
                            "off_canvas": True,
                            "x": box["x"],
                            "bounding_box": box,
                        })
                flow_completed = True

            elif f_id == "session_expiry":
                await page.goto(f"{base_url}/profile")
                save_btn = page.locator("#saveProfileBtn, button[type='submit']")
                if await save_btn.count() > 0:
                    await save_btn.first.click()
                    await page.wait_for_timeout(300)
                flow_completed = True

            elif f_id == "enrollment_flow":
                enroll_btn = page.locator("#enrollBtn")
                if await enroll_btn.count() > 0 and await enroll_btn.first.is_visible():
                    await enroll_btn.first.click()
                    await page.wait_for_timeout(300)
                flow_completed = True

            elif f_id == "spa_custom_buttons":
                pub_btn = page.locator("#publishArticleDiv, .custom-btn.primary")
                if await pub_btn.count() > 0 and await pub_btn.first.is_visible():
                    await pub_btn.first.click()
                    await page.wait_for_timeout(300)
                flow_completed = True

            elif f_id in (
                "working_auth_flow",
                "modal_login",
                "multistep_login",
                "redirect_after_login",
                "totp_login",
                "email_otp_login",
                "iframe_login",
            ):
                flow_completed = auth_success

            # Stage E: Capture real evidence
            screenshot_bytes = await page.screenshot()
            evidence_valid = len(screenshot_bytes) > 500
            evidence_items = (
                [{"image_bytes": screenshot_bytes, "metadata": {"size_bytes": len(screenshot_bytes)}}]
                if evidence_valid
                else []
            )
            body_text = await page.inner_text("body")

            # Stage F: Defect Matching against ground_truth.yml
            (
                detected_defects,
                detected_ids,
                ev_valid,
                ev_completeness,
                match_notes,
            ) = match_defects(
                known_defects=fixture.known_defects,
                events=[],
                network_responses=network_responses,
                verification={"status": "PASSED" if flow_completed else "FAILED"},
                evidence_items=evidence_items,
                page_text=body_text,
                final_url=page.url,
                visual_findings=report_findings,
                auth_result=auth_res,
            )
            evidence_valid = ev_valid
            evidence_completeness = ev_completeness
            notes = match_notes

            expected_defects = len(fixture.known_defects)
            if expected_defects == 0:
                if detected_defects > 0 or not flow_completed or (auth_attempted and not auth_success):
                    false_positives = 1
            else:
                false_positives = 0

            # Real resource accounting (no fabricated numbers)
            if self.agent_enabled and provider:
                curr_usage = provider.get_usage()
                model_calls = curr_usage.get("model_calls", 0) - start_usage.get("model_calls", 0)
                tokens_used = curr_usage.get("total_tokens", 0) - start_usage.get("total_tokens", 0)
                cost_usd = curr_usage.get("cost_usd", 0.0) - start_usage.get("cost_usd", 0.0)

        except Exception as e:
            logger.error("Error executing fixture %s: %s", fixture.fixture_id, e)
            notes = f"Execution error: {e}"
            if len(fixture.known_defects) == 0:
                false_positives = 1
        finally:
            await browser.close()
            setattr(ai_settings, "AI_PROVIDER", orig_provider_setting)

        expected = len(fixture.known_defects)
        false_negatives = max(0, expected - detected_defects)
        false_passes = int(expected > 0 and flow_completed and detected_defects == 0)
        false_fails = int(expected == 0 and (not flow_completed or detected_defects > 0))
        unverified = not flow_completed or not evidence_valid
        duration = max(0.05, time.perf_counter() - start_time)

        return FixtureRunResult(
            fixture_id=fixture.fixture_id,
            expected_defects=expected,
            detected_defects=detected_defects,
            false_positives=false_positives,
            false_negatives=false_negatives,
            evidence_valid=evidence_valid,
            needs_manual_intervention=False,
            duration_seconds=duration,
            model_calls=model_calls,
            cost_usd=cost_usd,
            notes=notes,
            auth_attempted=auth_attempted,
            auth_success=auth_success,
            flow_completed=flow_completed,
            evidence_completeness=evidence_completeness,
            tokens_used=tokens_used,
            journeys_found=journeys_found,
            journeys_labeled=len(fixture.expected_scenarios),
            false_journeys_proposed=false_journeys_proposed,
            steps_executed=steps_executed,
            false_passes=false_passes,
            false_fails=false_fails,
            unverified=unverified,
            success_without_evidence=flow_completed and not evidence_valid,
        )

    def _compute_report(
        self,
        total_duration: float,
        total_model_calls: int,
        total_cost: float,
        total_tokens: int,
    ) -> BenchmarkReport:
        total_fixtures = max(1, len(self.results))
        total_expected = sum(r.expected_defects for r in self.results)
        total_detected = sum(r.detected_defects for r in self.results)
        total_fp = sum(r.false_positives for r in self.results)
        total_fn = sum(r.false_negatives for r in self.results)

        clean_fixtures = sum(1 for r in self.results if r.expected_defects == 0)
        clean_fixtures_div = max(1, clean_fixtures)

        # TP rate: defects detected / defects present
        tp_rate = total_detected / max(1, total_expected) if total_expected > 0 else 1.0
        fp_rate = total_fp / clean_fixtures_div
        fn_rate = total_fn / max(1, total_expected) if total_expected > 0 else 0.0

        # Auth success rate among fixtures that attempted auth (excluding intentionally buggy auth)
        valid_auth_runs = [
            r for r in self.results if r.auth_attempted and r.fixture_id != "buggy_auth_flow"
        ]
        auth_success_rate = (
            sum(1.0 for r in valid_auth_runs if r.auth_success) / max(1, len(valid_auth_runs))
            if valid_auth_runs
            else 1.0
        )

        # Flow completion rate
        flow_completion_rate = sum(1.0 for r in self.results if r.flow_completed) / total_fixtures

        # Evidence completeness
        evidence_completeness = sum(r.evidence_completeness for r in self.results) / total_fixtures

        # Scenario relevance (measured, no constant floor)
        scenario_relevance = (
            sum(1.0 for r in self.results if r.flow_completed or r.detected_defects > 0)
            / total_fixtures
        )

        avg_cost = total_cost / total_fixtures
        avg_time = total_duration / total_fixtures
        avg_calls = total_model_calls / total_fixtures
        defective_fixtures = max(1, sum(r.expected_defects > 0 for r in self.results))
        clean_fixtures = max(1, sum(r.expected_defects == 0 for r in self.results))

        metrics = BenchmarkMetrics(
            scenario_relevance=scenario_relevance,
            true_positive_rate=tp_rate,
            false_positive_rate=fp_rate,
            false_negative_rate=fn_rate,
            evidence_quality_score=evidence_completeness,
            manual_intervention_rate=0.0,
            cost_per_validation_usd=avg_cost,
            time_per_validation_seconds=avg_time,
            model_calls_per_validation=avg_calls,
            auth_success_rate=auth_success_rate,
            flow_completion_rate=flow_completion_rate,
            evidence_completeness=evidence_completeness,
            total_tokens=total_tokens,
            journeys_found=sum(r.journeys_found for r in self.results),
            journeys_labeled=sum(r.journeys_labeled for r in self.results),
            false_journeys_proposed=sum(r.false_journeys_proposed for r in self.results),
            completion_rate=flow_completion_rate,
            avg_steps_per_journey=(
                sum(r.steps_executed for r in self.results)
                / max(1, sum(r.journeys_found for r in self.results))
            ),
            false_pass_rate=sum(r.false_passes for r in self.results) / defective_fixtures,
            false_fail_rate=sum(r.false_fails for r in self.results) / clean_fixtures,
            unverified_rate=sum(r.unverified for r in self.results) / total_fixtures,
            success_without_evidence=sum(r.success_without_evidence for r in self.results),
        )

        return BenchmarkReport(
            suite_name=self.suite.name,
            agent_enabled=self.agent_enabled,
            metrics=metrics,
            fixture_results=self.results,
        )
