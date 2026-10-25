import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectUpdate,
    EnvironmentConfig,
    ExecutionLimits,
    SafetyRestrictions,
    BrowserSettings,
)
from app.modules.projects.service import ProjectService


def test_project_create_schema():
    data = ProjectCreate(name="Test Project", base_url="http://localhost")
    assert data.name == "Test Project"
    assert data.base_url == "http://localhost"
    assert data.description is None


def test_project_create_schema_with_description():
    data = ProjectCreate(
        name="Test Project",
        base_url="http://localhost",
        description="A test",
    )
    assert data.description == "A test"


def test_project_update_schema_partial():
    data = ProjectUpdate(name="Updated")
    assert data.name == "Updated"
    assert data.base_url is None


def test_project_update_schema_empty():
    data = ProjectUpdate()
    assert data.name is None
    assert data.base_url is None


def test_project_create_accepts_all_brief_fields():
    cred_id = uuid.uuid4()
    data = ProjectCreate(
        name="Comprehensive Project",
        base_url="https://app.example.com",
        description="Full brief fields",
        product_goal="Verify checkout without regressions",
        env_config=EnvironmentConfig(target="staging", allowed_hosts=["app.example.com"]),
        execution_limits=ExecutionLimits(max_duration_seconds=600, max_agent_turns=50),
        safety_restrictions=SafetyRestrictions(production_access_allowed=False, payment_actions_allowed=False),
        browser_settings=BrowserSettings(viewport_width=1440, viewport_height=900),
        test_credentials_ref=cred_id,
    )
    assert data.product_goal == "Verify checkout without regressions"
    assert data.env_config.target == "staging"
    assert data.execution_limits.max_duration_seconds == 600
    assert data.execution_limits.max_agent_turns == 50
    assert data.safety_restrictions.production_access_allowed is False
    assert data.browser_settings.viewport_width == 1440
    assert data.test_credentials_ref == cred_id


def test_default_safety_restrictions_are_safe():
    safety = SafetyRestrictions()
    assert safety.production_access_allowed is False
    assert safety.payment_actions_allowed is False
    assert safety.account_deletion_allowed is False
    assert safety.destructive_action_allowlist == []
    assert safety.forbidden_routes == []
    assert safety.forbidden_selectors == []


@pytest.mark.asyncio
async def test_execution_limits_validation_rejects_too_short_duration():
    mock_db = MagicMock()
    service = ProjectService(mock_db)
    data = ProjectCreate(
        name="Too Short",
        base_url="https://app.example.com",
        execution_limits=ExecutionLimits(max_duration_seconds=10),
    )
    with pytest.raises(ValueError, match="max_duration_seconds must be at least 30"):
        await service._validate_create(data, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_execution_limits_validation_rejects_too_many_turns():
    mock_db = MagicMock()
    service = ProjectService(mock_db)
    data = ProjectCreate(
        name="Too Many Turns",
        base_url="https://app.example.com",
        execution_limits=ExecutionLimits(max_agent_turns=120),
    )
    with pytest.raises(ValueError, match="max_agent_turns must be at most 100"):
        await service._validate_create(data, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_production_access_requires_acknowledgment():
    mock_db = MagicMock()
    service = ProjectService(mock_db)
    # Production target with production access allowed, but without acknowledgment text
    data_missing = ProjectCreate(
        name="Prod Project",
        base_url="https://prod.example.com",
        description="Just a regular description",
        env_config=EnvironmentConfig(target="production"),
        safety_restrictions=SafetyRestrictions(production_access_allowed=True),
    )
    with pytest.raises(ValueError, match="Production access requires explicit acknowledgment"):
        await service._validate_create(data_missing, user_id=uuid.uuid4())

    # With proper acknowledgment
    data_valid = ProjectCreate(
        name="Prod Project Valid",
        base_url="https://prod.example.com",
        description="Production setup. I ACKNOWLEDGE production access for this environment.",
        env_config=EnvironmentConfig(target="production"),
        safety_restrictions=SafetyRestrictions(production_access_allowed=True),
    )
    # Should not raise
    await service._validate_create(data_valid, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_test_credentials_ref_must_belong_to_user():
    mock_db = MagicMock()
    service = ProjectService(mock_db)
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    cred_id = uuid.uuid4()

    mock_cred = MagicMock()
    mock_cred.user_id = user_b  # Owned by user B

    service.repo.db = mock_db
    with pytest.MonkeyPatch.context() as mp:
        mock_cred_repo = MagicMock()
        mock_cred_repo.get_by_id = AsyncMock(return_value=mock_cred)
        mp.setattr("app.modules.credentials.repository.CredentialRepository", lambda db: mock_cred_repo)

        data = ProjectCreate(
            name="Cred Test",
            base_url="https://app.example.com",
            test_credentials_ref=cred_id,
        )
        with pytest.raises(ValueError, match="test_credentials_ref must reference a credential owned by the user"):
            await service._validate_create(data, user_id=user_a)


def test_project_model_and_schema_logo_url():
    from app.modules.projects.models import Project
    from app.modules.projects.schemas import ProjectRead
    from datetime import datetime, timezone

    # 1. Fallback logo computed from base_url
    p = Project(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Quiza Ai",
        base_url="https://quiza-ai.vercel.app",
        env_config={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert p.logo_url == "https://www.google.com/s2/favicons?domain=quiza-ai.vercel.app&sz=128"
    read_dto = ProjectRead.model_validate(p)
    assert read_dto.logo_url == "https://www.google.com/s2/favicons?domain=quiza-ai.vercel.app&sz=128"

    # 2. Custom extracted logo from analysis in env_config
    p_with_logo = Project(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Quiza Ai",
        base_url="https://quiza-ai.vercel.app",
        env_config={"logo_url": "https://quiza-ai.vercel.app/brand-logo.svg"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert p_with_logo.logo_url == "https://quiza-ai.vercel.app/brand-logo.svg"
    read_with_logo = ProjectRead.model_validate(p_with_logo)
    assert read_with_logo.logo_url == "https://quiza-ai.vercel.app/brand-logo.svg"
