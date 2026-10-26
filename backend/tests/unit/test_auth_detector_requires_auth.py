import uuid

import pytest

from app.engine.browser.auth import AuthSignalBundle
from app.engine.exploration.discovery import auth_detector as auth_detector_module
from app.engine.exploration.discovery.auth_detector import AuthDetector
from app.modules.product_graph.schemas import Page


def _bundle(**overrides) -> AuthSignalBundle:
    values = {
        "url_path_is_auth": False,
        "visible_password_input_count": 0,
        "visible_email_input_count": 0,
        "visible_otp_input_count": 0,
        "has_remember_me_checkbox": False,
        "has_forgot_password_link": False,
    }
    values.update(overrides)
    return AuthSignalBundle(**values)


@pytest.mark.asyncio
async def test_dashboard_url_alone_does_not_require_auth(monkeypatch):
    async def fake_observe(page, url=None):
        return _bundle()

    monkeypatch.setattr(auth_detector_module, "observe_auth_signals", fake_observe)
    page = Page(project_id=uuid.uuid4(), url_pattern="/dashboard", requires_auth=False)

    await AuthDetector().inspect_page_auth(object(), page)

    assert page.requires_auth is False


@pytest.mark.asyncio
async def test_auth_url_without_dom_signals_does_not_require_auth(monkeypatch):
    async def fake_observe(page, url=None):
        return _bundle(url_path_is_auth=True)

    monkeypatch.setattr(auth_detector_module, "observe_auth_signals", fake_observe)
    page = Page(project_id=uuid.uuid4(), url_pattern="/login", requires_auth=False)

    await AuthDetector().inspect_page_auth(object(), page)

    assert page.requires_auth is False


@pytest.mark.asyncio
async def test_visible_password_input_requires_auth(monkeypatch):
    async def fake_observe(page, url=None):
        return _bundle(visible_password_input_count=1)

    monkeypatch.setattr(auth_detector_module, "observe_auth_signals", fake_observe)
    page = Page(project_id=uuid.uuid4(), url_pattern="/login", requires_auth=False)

    await AuthDetector().inspect_page_auth(object(), page)

    assert page.requires_auth is True
