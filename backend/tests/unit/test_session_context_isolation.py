import pytest

from app.engine.browser.session import BrowserSession


def test_job_id_stored_on_session():
    assert BrowserSession().job_id is None
    assert BrowserSession(job_id="job-abc").job_id == "job-abc"


@pytest.mark.asyncio
async def test_fresh_context_requires_started_session():
    with pytest.raises(RuntimeError, match="not started"):
        await BrowserSession().fresh_context()


@pytest.mark.asyncio
async def test_start_twice_yields_fresh_isolated_context_with_egress_guard():
    session = BrowserSession(headless=True, job_id="job-42")
    await session.start()
    try:
        assert session.is_started
        assert session.job_id == "job-42"

        first_context = session.context
        first_browser = session._browser
        await first_context.add_cookies(
            [{"name": "kova_job", "value": "1", "domain": "example.com", "path": "/"}]
        )
        assert len(await session.context.cookies()) == 1

        # Second start() must not relaunch the browser; it swaps in a clean context.
        await session.start()
        assert session._browser is first_browser
        assert session.context is not first_context
        assert first_context.is_closed()
        assert await session.context.cookies() == []

        # Egress interception is re-armed on the new context/page.
        with pytest.raises(Exception, match="ERR_BLOCKED_BY_CLIENT"):
            await session.page.goto("http://169.254.169.254/latest/meta-data/")
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_fresh_context_resets_error_capture_state():
    session = BrowserSession(headless=True, job_id="job-43")
    await session.start()
    try:
        session.network_errors.append({"url": "https://x.test/err"})
        session.console_errors.append("boom")
        session.failed_requests.append({"url": "https://x.test/fail"})
        await session.fresh_context()
        assert session.network_errors == []
        assert session.console_errors == []
        assert session.failed_requests == []
        assert session.is_started
    finally:
        await session.close()
