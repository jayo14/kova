import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import get_session
from app.main import app
from app.modules.integrations.github.webhook import verify_github_signature
from app.modules.integrations.gitlab.webhook import verify_gitlab_token
from app.modules.integrations.models import Integration, IntegrationEvent
from app.modules.integrations.orchestrator import (
    IntegrationOrchestrator,
    format_pr_comment,
    parse_kova_config,
)
from app.modules.integrations.repository import IntegrationRepository
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.validation.schemas import (
    FlowRef,
    FlowValidationResult,
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)


@pytest.mark.asyncio
async def test_github_webhook_signature_verification(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="gh-user@kova.local")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="GH Project", base_url="https://example.com")
        db_session.add_all([user, project])
        await db_session.commit()

        repo = IntegrationRepository(db_session)
        secret = "super-secret-gh-key"
        integration = await repo.create(
            project_id=project.id,
            provider="github",
            provider_repo_id="octocat/hello-world",
            webhook_secret=secret,
        )

        payload = {
            "action": "opened",
            "repository": {"full_name": "octocat/hello-world"},
            "pull_request": {"number": 42},
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        valid_sig = f"sha256={valid_digest}"
        invalid_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Correct signature
            resp = await client.post(
                "/api/v1/integrations/github/webhook",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": valid_sig,
                    "X-GitHub-Event": "pull_request",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "accepted"

            # 2. Wrong signature -> 401
            resp_bad = await client.post(
                "/api/v1/integrations/github/webhook",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": invalid_sig,
                    "X-GitHub-Event": "pull_request",
                },
            )
            assert resp_bad.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_gitlab_webhook_token_verification(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="gl-user@kova.local")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="GL Project", base_url="https://example.com")
        db_session.add_all([user, project])
        await db_session.commit()

        repo = IntegrationRepository(db_session)
        secret = "gl-secret-token"
        integration = await repo.create(
            project_id=project.id,
            provider="gitlab",
            provider_repo_id="gitlab-org/gitlab",
            webhook_secret=secret,
        )

        payload = {
            "event_type": "merge_request",
            "object_attributes": {"action": "open", "iid": 7},
            "project": {"id": 1234, "path_with_namespace": "gitlab-org/gitlab"},
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Correct token
            resp = await client.post(
                "/api/v1/integrations/gitlab/webhook",
                json=payload,
                headers={
                    "X-Gitlab-Token": secret,
                    "X-Gitlab-Event": "Merge Request Hook",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "accepted"

            # 2. Invalid token -> 401
            resp_bad = await client.post(
                "/api/v1/integrations/gitlab/webhook",
                json=payload,
                headers={
                    "X-Gitlab-Token": "wrong-token",
                    "X-Gitlab-Event": "Merge Request Hook",
                },
            )
            assert resp_bad.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_github_webhook_triggers_orchestrator(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="gh2@kova.local")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="GH2", base_url="https://example.com")
        db_session.add_all([user, project])
        await db_session.commit()

        repo = IntegrationRepository(db_session)
        secret = "test-secret"
        integration = await repo.create(
            project_id=project.id,
            provider="github",
            provider_repo_id="testorg/testrepo",
            webhook_secret=secret,
        )

        payload = {
            "action": "synchronize",
            "repository": {"full_name": "testorg/testrepo"},
            "pull_request": {"number": 10},
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/integrations/github/webhook",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": f"sha256={valid_digest}",
                    "X-GitHub-Event": "pull_request",
                    "X-GitHub-Delivery": "delivery-1234",
                },
            )
            assert resp.status_code == 200
            event_id = uuid.UUID(resp.json()["event_id"])

            # Verify event was persisted
            from sqlalchemy import select
            res = await db_session.execute(select(IntegrationEvent).where(IntegrationEvent.id == event_id))
            ev = res.scalar_one_or_none()
            assert ev is not None
            assert ev.event_type == "pull_request.synchronize"
            assert ev.integration_id == integration.id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_orchestrator_runs_validation_and_posts_comment(db_session):
    user = User(id=uuid.uuid4(), email="orch@kova.local")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="Orch Project", base_url="https://example.com")
    db_session.add_all([user, project])
    await db_session.commit()

    repo = IntegrationRepository(db_session)
    integration = await repo.create(
        project_id=project.id,
        provider="github",
        provider_repo_id="org/repo",
        webhook_secret="s",
    )
    event = await repo.create_event(
        integration_id=integration.id,
        provider_event_id="e1",
        event_type="pull_request.opened",
        payload={"pull_request": {"number": 5}},
    )

    flow_id = uuid.uuid4()
    mock_diff_fetcher = MagicMock()
    mock_diff_fetcher.fetch_pr_diff = AsyncMock(return_value="--- a/src/index.ts\n+++ b/src/index.ts\n@@ -1 +1 @@\n-a\n+b")
    mock_diff_fetcher.fetch_kova_config = AsyncMock(return_value=None)

    mock_planner = MagicMock()
    mock_plan = MagicMock()
    mock_plan.steps = [MagicMock(flow_id=flow_id, flow_name="Login Flow")]
    mock_impact = ImpactReport(changed_files=["src/index.ts"], graph_traversal_log=["[Impact] File src/index.ts"])
    mock_planner.plan = AsyncMock(return_value=(mock_plan, mock_impact))

    mock_runner = MagicMock()
    mock_report = ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=project.id),
        impact_report=mock_impact,
        results=[
            FlowValidationResult(
                flow_id=flow_id,
                flow_name="Login Flow",
                role="target",
                status="passed",
                duration_ms=150,
            )
        ],
        overall_status="passed",
        duration_ms=150,
    )
    mock_runner.run = AsyncMock(return_value=mock_report)

    mock_github_client = MagicMock()
    mock_github_client.get_pr_comment_id_by_marker = AsyncMock(return_value=None)
    mock_github_client.post_pr_comment = AsyncMock(return_value={"id": 100})
    mock_github_client.post_or_update_pr_comment = AsyncMock(return_value={"id": 100})

    orchestrator = IntegrationOrchestrator(
        db=db_session,
        diff_fetcher=mock_diff_fetcher,
        planner=mock_planner,
        runner=mock_runner,
        github_client=mock_github_client,
    )

    res_report = await orchestrator.handle_event(event)
    assert res_report.overall_status == "passed"
    mock_github_client.post_or_update_pr_comment.assert_called_once()
    call_args = mock_github_client.post_or_update_pr_comment.call_args[1]
    assert call_args["repo"] == "org/repo"
    assert call_args["pr_number"] == 5
    assert "## Kova Validation — ✅ passed" in call_args["body"]
    assert "Login Flow" in call_args["body"]


@pytest.mark.asyncio
async def test_orchestrator_updates_existing_comment(db_session):
    user = User(id=uuid.uuid4(), email="update-comm@kova.local")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="Proj", base_url="https://example.com")
    db_session.add_all([user, project])
    await db_session.commit()

    repo = IntegrationRepository(db_session)
    integration = await repo.create(
        project_id=project.id,
        provider="github",
        provider_repo_id="org/repo-update",
        webhook_secret="s",
    )
    event = await repo.create_event(
        integration_id=integration.id,
        provider_event_id="e2",
        event_type="pull_request.synchronize",
        payload={"pull_request": {"number": 12}},
    )

    mock_diff_fetcher = MagicMock()
    mock_diff_fetcher.fetch_pr_diff = AsyncMock(return_value="--- a/file.ts\n+++ b/file.ts\n@@ -1 +1 @@")
    mock_diff_fetcher.fetch_kova_config = AsyncMock(return_value=None)

    mock_planner = MagicMock()
    mock_plan = MagicMock()
    mock_plan.steps = []
    mock_impact = ImpactReport()
    mock_planner.plan = AsyncMock(return_value=(mock_plan, mock_impact))

    mock_runner = MagicMock()
    mock_report = ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=project.id),
        impact_report=mock_impact,
        results=[],
        overall_status="passed",
    )
    mock_runner.run = AsyncMock(return_value=mock_report)

    mock_github_client = MagicMock()
    # Mocking that comment already exists with ID 999
    mock_github_client.get_pr_comment_id_by_marker = AsyncMock(return_value=999)
    mock_github_client.update_pr_comment = AsyncMock(return_value={"id": 999})
    # If using real GitHubClient logic
    from app.modules.integrations.github.client import GitHubClient
    client_instance = GitHubClient(token="mock")
    client_instance.get_pr_comment_id_by_marker = AsyncMock(return_value=999)
    client_instance.update_pr_comment = AsyncMock(return_value={"id": 999})
    client_instance.post_pr_comment = AsyncMock()

    orchestrator = IntegrationOrchestrator(
        db=db_session,
        diff_fetcher=mock_diff_fetcher,
        planner=mock_planner,
        runner=mock_runner,
        github_client=client_instance,
    )

    await orchestrator.handle_event(event)
    client_instance.update_pr_comment.assert_called_once()
    client_instance.post_pr_comment.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_handles_no_graph(db_session):
    report = ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=uuid.uuid4()),
        impact_report=ImpactReport(),
        overall_status="no_graph",
    )
    comment = format_pr_comment(report, event_id=uuid.uuid4(), project_id=report.request.project_id)
    assert "## Kova Validation — 🚫 no graph" in comment
    assert "⚠️ No Product Graph available. Run Product Discovery first." in comment
    assert "Go to Discovery" in comment


@pytest.mark.asyncio
async def test_orchestrator_handles_no_flows_affected(db_session):
    report = ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=uuid.uuid4()),
        impact_report=ImpactReport(),
        overall_status="no_flows",
    )
    comment = format_pr_comment(report, event_id=uuid.uuid4(), project_id=report.request.project_id)
    assert "## Kova Validation — 🤷 no flows affected" in comment
    assert "🤷 No flows affected by this PR. No validation needed." in comment


@pytest.mark.asyncio
async def test_kova_yml_config_overrides(db_session):
    user = User(id=uuid.uuid4(), email="config@kova.local")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="ConfigProj", base_url="https://example.com")
    db_session.add_all([user, project])
    await db_session.commit()

    repo = IntegrationRepository(db_session)
    integration = await repo.create(
        project_id=project.id,
        provider="github",
        provider_repo_id="org/config-repo",
        webhook_secret="s",
    )
    event = await repo.create_event(
        integration_id=integration.id,
        provider_event_id="e3",
        event_type="pull_request.opened",
        payload={"pull_request": {"number": 1}},
    )

    yaml_config = """
base_url: https://staging.myapp.com
persona: student
only_flows:
  - auth_flow
rediscover_on_config_change: false
"""
    mock_diff_fetcher = MagicMock()
    mock_diff_fetcher.fetch_pr_diff = AsyncMock(return_value="--- a/README.md\n+++ b/README.md")
    mock_diff_fetcher.fetch_kova_config = AsyncMock(return_value=yaml_config)

    step1 = MagicMock(flow_id=uuid.uuid4(), flow_name="auth_flow")
    step2 = MagicMock(flow_id=uuid.uuid4(), flow_name="course_flow")
    mock_plan = MagicMock()
    mock_plan.steps = [step1, step2]

    mock_planner = MagicMock()
    mock_planner.plan = AsyncMock(return_value=(mock_plan, ImpactReport()))

    mock_runner = MagicMock()
    mock_runner.run = AsyncMock(return_value=ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=project.id),
        impact_report=ImpactReport(),
        overall_status="passed",
    ))

    mock_gh = MagicMock()
    mock_gh.post_or_update_pr_comment = AsyncMock()

    orchestrator = IntegrationOrchestrator(
        db=db_session,
        diff_fetcher=mock_diff_fetcher,
        planner=mock_planner,
        runner=mock_runner,
        github_client=mock_gh,
    )

    await orchestrator.handle_event(event)

    # Assert plan was filtered to only auth_flow
    assert len(mock_plan.steps) == 1
    assert mock_plan.steps[0].flow_name == "auth_flow"
