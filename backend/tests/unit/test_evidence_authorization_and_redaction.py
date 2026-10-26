import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.modules.executions.reporting import sanitize_payload, sanitize_text
from app.modules.executions.evidence_service import EvidenceService


def test_sanitize_text_compound_secrets():
    """Verify sanitize_text redacts compound credentials, headers, and tokens."""
    # Bearer, Basic, Auth headers
    text1 = "Error occurred with Authorization: Bearer eyJhbGciOi.eyJzdWIi.signature and Basic dXNlcjpwYXNz"
    sanitized1 = sanitize_text(text1)
    assert "eyJhbGciOi" not in sanitized1
    assert "dXNlcjpwYXNz" not in sanitized1
    assert "Authorization: [REDACTED]" in sanitized1

    # Database URL with user/pass and query params
    text2 = "Connecting to postgres://admin:super_secret_pw@db.internal:5432/prod?sslmode=require"
    sanitized2 = sanitize_text(text2)
    assert "super_secret_pw" not in sanitized2
    assert "admin" not in sanitized2
    assert "sslmode" not in sanitized2
    assert "postgres://db.internal:5432/prod?[REDACTED]" in sanitized2

    # Standalone JWT
    text3 = "Received token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature"
    sanitized3 = sanitize_text(text3)
    assert "doNotLeakThisSignature" not in sanitized3
    assert "[JWT REDACTED]" in sanitized3

    # JSON in DOM excerpts
    text4 = '<div data-state="{\\"password\\": \\"hunter2\\", \\"apiKey\\": \\"live_key_999\\", \\"clientSecret\\": \\"sec_888\\"}">'
    sanitized4 = sanitize_text(text4)
    assert "hunter2" not in sanitized4
    assert "live_key_999" not in sanitized4
    assert "sec_888" not in sanitized4
    assert '[REDACTED]' in sanitized4

    # Key-value pairs in text
    text5 = "Failed request: session_id=sess_abc123456789; private_key=pk_live_xyz; client_secret=cs_123"
    sanitized5 = sanitize_text(text5)
    assert "sess_abc123456789" not in sanitized5
    assert "pk_live_xyz" not in sanitized5
    assert "cs_123" not in sanitized5


def test_sanitize_payload_recursive():
    """Verify sanitize_payload recursively redacts compound secrets in nested structures."""
    payload = {
        "user": {
            "name": "Alice",
            "session_id": "sess_secret_token",
            "access_token": "at_999",
            "refresh_token": "rt_888",
            "client_secret": "cs_777",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----",
        },
        "nested_list": [
            {"jwt": "eyJhbGciOi.eyJzdWIi.xyz", "id_token": "idt_555"},
            {"safe_field": 42},
        ],
    }
    sanitized = sanitize_payload(payload)
    assert sanitized["user"]["name"] == "Alice"
    assert sanitized["user"]["session_id"] == "[REDACTED]"
    assert sanitized["user"]["access_token"] == "[REDACTED]"
    assert sanitized["user"]["refresh_token"] == "[REDACTED]"
    assert sanitized["user"]["client_secret"] == "[REDACTED]"
    assert sanitized["user"]["private_key"] == "[REDACTED]"
    assert sanitized["nested_list"][0]["jwt"] == "[REDACTED]"
    assert sanitized["nested_list"][0]["id_token"] == "[REDACTED]"
    assert sanitized["nested_list"][1]["safe_field"] == 42


@pytest.mark.asyncio
async def test_evidence_service_sanitizes_dom_and_a11y():
    """Verify EvidenceService sanitizes DOM snapshots and A11y trees upon creation."""
    mock_repo = MagicMock()
    mock_repo.create = AsyncMock(return_value=MagicMock(
        id=uuid.uuid4(),
        created_at=None,
        status="verified",
        storage_key="test.png",
    ))

    service = EvidenceService(AsyncMock())
    service.repo = mock_repo

    exec_id = uuid.uuid4()
    dirty_dom = '<form><input type="password" name="password=supersecret" value="password=supersecret"/></form>'
    dirty_a11y = 'button "Submit Authorization: Bearer eyJsecret"'

    await service.create(
        execution_id=exec_id,
        type="screenshot",
        title="Check password=hidden",
        purpose="verification",
        step_id="step-1",
        dom_snapshot=dirty_dom,
        a11y_tree=dirty_a11y,
        note="User note token=token123",
    )

    call_kwargs = mock_repo.create.call_args[1]
    assert "supersecret" not in call_kwargs["dom_snapshot"]
    assert "Authorization: [REDACTED]" in call_kwargs["a11y_tree"]
    assert "token123" not in call_kwargs["note"]
    assert "password=[REDACTED]" in call_kwargs["title"]


@pytest.mark.asyncio
async def test_cross_project_evidence_authorization():
    """Verify cross-project execution and evidence access is rejected."""
    from app.api.routes.executions import _verify_execution_ownership

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    exec_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    project_id = uuid.uuid4()

    mock_execution = MagicMock(id=exec_id, flow_id=flow_id)
    mock_flow = MagicMock(id=flow_id, project_id=project_id)

    mock_db = MagicMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = mock_flow
    mock_db.execute = AsyncMock(return_value=mock_exec_result)

    with patch("app.modules.executions.repository.ExecutionRepository.get_by_id", AsyncMock(return_value=mock_execution)), \
         patch("app.modules.projects.repository.ProjectRepository.get_by_id_and_user") as mock_proj:

        # User A owns the project
        mock_proj.return_value = MagicMock(id=project_id, user_id=user_a)
        res_a = await _verify_execution_ownership(mock_db, exec_id, user_a)
        assert res_a == mock_execution

        # User B does NOT own the project -> 404
        mock_proj.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await _verify_execution_ownership(mock_db, exec_id, user_b)
        assert exc_info.value.status_code == 404
