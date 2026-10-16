"""Main integration orchestrator: webhook → diff → impact → run → report → comment."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.modules.executions.reporting import (
    ReportGenerator,
    generate_validation_signature,
)
from app.modules.integrations.diff_fetcher import DiffFetcher, extract_changed_files_from_diff
from app.modules.integrations.github.client import GitHubClient
from app.modules.integrations.gitlab.client import GitLabClient
from app.modules.integrations.models import Integration, IntegrationEvent
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.schemas import KovaConfig
from app.modules.validation.models import SignedUrlModel, ValidationReportModel
from app.modules.validation.planner import TargetedRegressionPlanner
from app.modules.validation.runner import ValidationRunner
from app.modules.validation.schemas import (
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)

logger = logging.getLogger(__name__)


def parse_kova_config(yaml_content: Optional[str]) -> KovaConfig:
    """Parse .kova.yml file safely into KovaConfig model."""
    if not yaml_content or not yaml_content.strip():
        return KovaConfig()
    try:
        data = yaml.safe_load(yaml_content)
        if isinstance(data, dict):
            return KovaConfig(**data)
    except Exception as e:
        logger.warning("Failed to parse .kova.yml: %s", e)
    return KovaConfig()


def format_pr_comment(
    report: ValidationReport,
    event_id: uuid.UUID,
    project_id: uuid.UUID,
    base_url: str = "http://localhost:3000",
) -> str:
    """Format markdown PR comment according to Chunk 14 specification."""
    status_icons = {
        "passed": "✅ passed",
        "failed": "❌ failed",
        "unverified": "⚠️ unverified",
        "no_graph": "🚫 no graph",
        "no_flows": "🤷 no flows affected",
    }
    badge = status_icons.get(report.overall_status, report.overall_status)
    settings_url = f"{base_url}/projects/{project_id}/settings"
    discovery_url = f"{base_url}/projects/{project_id}/discovery"

    lines = [f"## Kova Validation — {badge}", ""]

    if report.overall_status == "no_graph":
        lines.append("⚠️ No Product Graph available. Run Product Discovery first. [Go to Discovery](%s)" % discovery_url)
        lines.append("")
        lines.append("<!-- kova-validation: %s -->" % event_id)
        lines.append("Powered by Kova. [Configure](%s)" % settings_url)
        return "\n".join(lines)

    if report.overall_status == "no_flows":
        lines.append("🤷 No flows affected by this PR. No validation needed.")
        lines.append("")
        lines.append("<!-- kova-validation: %s -->" % event_id)
        lines.append("Powered by Kova. [Configure](%s)" % settings_url)
        return "\n".join(lines)

    # Summary line
    flow_count = len(report.results)
    duration_sec = report.duration_ms / 1000.0
    affected_names = [r.flow_name for r in report.results] or ["None"]
    lines.append(
        f"Ran {flow_count} flows in {duration_sec:.1f}s. Affected: {', '.join(affected_names)}. Duration: {duration_sec:.1f}s."
    )
    lines.append("")

    # Results Table
    lines.append("| Flow | Role | Status | Duration |")
    lines.append("| --- | --- | --- | --- |")
    for r in report.results:
        st_icon = "✅ passed" if r.status == "passed" else ("❌ failed" if r.status == "failed" else r.status)
        lines.append(f"| {r.flow_name} | {r.role} | {st_icon} | {r.duration_ms}ms |")
    lines.append("")

    # Failures detail
    failures = [r for r in report.results if r.status in ("failed", "error")]
    if failures:
        lines.append("### Failures Detail")
        for f in failures:
            lines.append(f"- **{f.flow_name}**: {f.failure_reason or 'Validation check failed'}")
            if f.evidence_ids and report.signed_url:
                lines.append(f"  [View Evidence]({report.signed_url}#evidence-embed-{f.flow_id})")
        lines.append("")

    # Link to full report
    if report.signed_url:
        lines.append(f"[Full report with evidence]({report.signed_url})")
        lines.append("")

    # Collapsible graph traversal log
    if report.impact_report.graph_traversal_log:
        lines.append("<details>")
        lines.append("<summary>Why did Kova run these flows?</summary>")
        lines.append("")
        lines.append("```")
        for entry in report.impact_report.graph_traversal_log:
            lines.append(entry)
        lines.append("```")
        lines.append("</details>")
        lines.append("")

    # Marker and footer
    lines.append(f"<!-- kova-validation: {event_id} -->")
    lines.append(f"Powered by Kova. [Configure]({settings_url})")

    return "\n".join(lines)


class IntegrationOrchestrator:
    """Coordinates PR webhook events through change impact, execution, and comments."""

    def __init__(
        self,
        db: AsyncSession,
        diff_fetcher: Optional[DiffFetcher] = None,
        planner: Optional[TargetedRegressionPlanner] = None,
        runner: Optional[ValidationRunner] = None,
        report_generator: Optional[ReportGenerator] = None,
        github_client: Optional[GitHubClient] = None,
        gitlab_client: Optional[GitLabClient] = None,
    ):
        self.db = db
        self.repo = IntegrationRepository(db)
        self.diff_fetcher = diff_fetcher or DiffFetcher(self.repo)
        self.planner = planner or TargetedRegressionPlanner(db)
        self.runner = runner or ValidationRunner(db)
        self.report_generator = report_generator or ReportGenerator(db)
        self.github_client = github_client
        self.gitlab_client = gitlab_client

    async def handle_event(
        self,
        event: IntegrationEvent,
        pr_or_mr_id: Optional[int] = None,
        base_api_url: str = "http://localhost:8000",
    ) -> ValidationReport:
        """Run complete webhook automation pipeline."""
        event_id = event.id
        # 1. Mark event processing
        await self.repo.update_event(event_id, status="processing")

        integration = await self.repo.get_by_id(event.integration_id)
        if not integration:
            await self.repo.update_event(event_id, status="failed", error="Integration not found")
            raise ValueError(f"Integration {event.integration_id} not found")

        # Extract PR/MR number
        pr_num = pr_or_mr_id
        if pr_num is None:
            payload = event.payload or {}
            if "pull_request" in payload:
                pr_num = payload["pull_request"].get("number")
            elif "object_attributes" in payload:
                pr_num = payload["object_attributes"].get("iid")
            elif "number" in payload:
                pr_num = payload.get("number")
        if not pr_num:
            pr_num = 1

        try:
            # 2. Fetch diff
            diff_text = await self.diff_fetcher.fetch_pr_diff(integration, pr_num)
            changed_files = extract_changed_files_from_diff(diff_text)

            # 3. Read .kova.yml config
            kova_config_raw = await self.diff_fetcher.fetch_kova_config(integration)
            config = parse_kova_config(kova_config_raw)

            # 4. If .kova.yml changed and rediscover_on_config_change is enabled, trigger rediscovery
            if any(f.endswith(".kova.yml") or f == ".kova.yml" for f in changed_files):
                if config.rediscover_on_config_change:
                    try:
                        from app.engine.exploration.service import ExplorationService
                        exp_svc = ExplorationService(self.db)
                        logger.info("Triggering incremental re-discovery for project %s due to .kova.yml change", integration.project_id)
                        await exp_svc.start_exploration(integration.project_id)
                    except Exception as e:
                        logger.warning("Incremental re-discovery trigger encountered exception: %s", e)

            # 5. Plan validation
            vreq = ValidationRequest(
                project_id=integration.project_id,
                diff_content=diff_text,
                changed_files=changed_files,
                base_url=config.base_url,
                persona=config.persona,
                timeout_seconds=config.timeout_seconds,
            )
            plan, impact = await self.planner.plan(vreq)

            # 6. Apply .kova.yml config filters
            if plan and (config.only_flows or config.skip_flows):
                filtered_steps = []
                for s in plan.steps:
                    flow_id_str = str(s.flow_id)
                    name = s.flow_name or ""
                    if config.only_flows and not (name in config.only_flows or flow_id_str in config.only_flows):
                        continue
                    if config.skip_flows and (name in config.skip_flows or flow_id_str in config.skip_flows):
                        continue
                    filtered_steps.append(s)
                plan.steps = filtered_steps

            # 7. Execute validation
            report = await self.runner.run(vreq)

            # 8. Generate and persist signed report URL
            sig = generate_validation_signature(report.id)
            signed_url = f"{base_api_url}/api/v1/validations/{report.id}/report?signature={sig}"
            expiry_ts = int(sig.split(".", 1)[0])
            expires_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
            report.signed_url = signed_url

            try:
                val_model = await self.db.get(ValidationReportModel, report.id)
                if not val_model:
                    val_model = ValidationReportModel(
                        id=report.id,
                        project_id=integration.project_id,
                        overall_status=report.overall_status,
                        duration_ms=getattr(report, "duration_ms", 0),
                        request=report.request.model_dump(mode="json") if hasattr(report.request, "model_dump") else {},
                        impact_report=report.impact_report.model_dump(mode="json") if hasattr(report.impact_report, "model_dump") else {},
                        results=[r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in getattr(report, "results", [])],
                        evidence_summary=getattr(report, "evidence_summary", {}),
                        signed_url=signed_url,
                        started_at=getattr(report, "started_at", datetime.now(timezone.utc)),
                        finished_at=getattr(report, "finished_at", datetime.now(timezone.utc)),
                    )
                    self.db.add(val_model)
                    await self.db.flush()

                self.db.add(
                    SignedUrlModel(
                        id=uuid.uuid4(),
                        validation_id=report.id,
                        url=signed_url,
                        signature=sig,
                        expires_at=expires_dt,
                    )
                )
                await self.db.commit()
            except Exception as sign_err:
                logger.warning("Failed to persist signed report URL: %s", sign_err)
                await self.db.rollback()

            # 9. Format PR comment
            comment_body = format_pr_comment(
                report=report,
                event_id=event_id,
                project_id=integration.project_id,
                base_url=settings.FRONTEND_URL,
            )

            # 10. Post or update PR comment via VCS client
            _, decrypted_token = await self.repo.get_decrypted_secrets(integration)
            if integration.provider == "github":
                gh = self.github_client or GitHubClient(token=decrypted_token)
                await gh.post_or_update_pr_comment(
                    repo=integration.provider_repo_id,
                    pr_number=pr_num,
                    body=comment_body,
                    marker="<!-- kova-validation",
                )
            elif integration.provider == "gitlab":
                gl = self.gitlab_client or GitLabClient(token=decrypted_token)
                await gl.post_or_update_mr_comment(
                    project_id=integration.provider_repo_id,
                    mr_iid=pr_num,
                    body=comment_body,
                    marker="<!-- kova-validation",
                )

            # 11. Mark event completed
            await self.repo.update_event(event_id, status="completed", validation_id=report.id)
            return report

        except Exception as e:
            logger.exception("Orchestrator failed for event %s: %s", event_id, e)
            await self.repo.update_event(event_id, status="failed", error=str(e))
            raise
