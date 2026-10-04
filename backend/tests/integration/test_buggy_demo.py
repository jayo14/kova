import asyncio
import socket
import threading
import uuid
from http.server import HTTPServer
import pytest

from app.config.settings import settings
from app.engine.execution.runner import FlowRunner
from app.modules.executions.models import ExecutionStatus
from app.modules.projects.service import ProjectService
from app.modules.flows.repository import FlowRepository
from pathlib import Path
import importlib.util

_server_path = Path(__file__).resolve().parents[3] / "examples" / "buggy-demo" / "server.py"
_spec = importlib.util.spec_from_file_location("buggy_demo_server", _server_path)
_buggy_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_buggy_demo)
BuggyDemoHandler = _buggy_demo.BuggyDemoHandler



def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def demo_server():
    port = get_free_port()
    server = HTTPServer(("127.0.0.1", port), BuggyDemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.mark.asyncio
async def test_demo_project_creation_and_flows(db_session):
    from app.modules.users.repository import UserRepository
    user_repo = UserRepository(db_session)
    user_id = uuid.uuid4()
    await user_repo.get_or_create(user_id=user_id, email="demo@example.com")

    service = ProjectService(db_session)
    project = await service.create_demo_project(
        user_id=user_id,
        base_url="http://127.0.0.1:8090",
    )
    assert project.name == "Buggy Demo App"
    assert project.base_url == "http://127.0.0.1:8090"

    flow_repo = FlowRepository(db_session)
    flows = await flow_repo.list_by_project(project.id)
    assert len(flows) == 2

    flow_names = {f.name for f in flows}
    assert "Contact Form Submission" in flow_names
    assert "User Authentication" in flow_names



@pytest.mark.asyncio
async def test_kova_fails_bug_1_contact_network_error(demo_server):
    """Kova must fail Bug 1: UI reports success but POST /api/contact returned 500."""
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    flow_steps = [
        {"type": "navigate", "url": f"{demo_server}/contact"},
        {"type": "wait", "value": "300"},
        {"type": "type", "target": "input[name='name']", "value": "Kova Tester"},
        {"type": "type", "target": "input[name='email']", "value": "tester@example.com"},
        {"type": "type", "target": "textarea[name='message']", "value": "Testing planted 500 network bug"},
        {"type": "click", "target": "button[type='submit']"},
        {"type": "wait", "value": "1000"},
    ]

    result = await runner.execute(
        execution_id=exec_id,
        flow_steps=flow_steps,
        success_condition={"text_visible": "Thank"},
    )

    assert result["success"] is False
    assert result["state"] == ExecutionStatus.FAILED.value
    assert "UI reported success but request POST /api/contact returned 500" in result["error"]


@pytest.mark.asyncio
async def test_kova_fails_bug_2_broken_login_verification(demo_server):
    """Kova must fail Bug 2: Login flow fails verification and user is stranded on /login."""
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    flow_steps = [
        {"type": "navigate", "url": f"{demo_server}/login"},
        {"type": "wait", "value": "300"},
        {"type": "type", "target": "input[name='email']", "value": "user@example.com"},
        {"type": "type", "target": "input[name='password']", "value": "SecretPassword123!"},
        {"type": "click", "target": "button[type='submit']"},
        {"type": "wait", "value": "1000"},
    ]

    result = await runner.execute(
        execution_id=exec_id,
        flow_steps=flow_steps,
        success_condition={"auth_verified": {"auth_path": "/login"}},
    )

    assert result["success"] is False
    assert result["state"] == ExecutionStatus.FAILED.value
    assert "Verification failed" in result["error"]
    assert "url_changed_from" in result["error"] or "element_absent" in result["error"]
