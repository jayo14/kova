import asyncio
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Thread
import pytest

from app.engine.browser.session import BrowserSession
from app.engine.browser.readiness import ReadinessWaiter
from app.engine.browser.platform_wake import detect_platform_wake


class LatencyFixtureHandler(BaseHTTPRequestHandler):
    render_wake_counter = 0

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP logs during tests
        pass

    def do_GET(self):
        if self.path == "/fast":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Fast Page</title></head><body><h1>Hello World</h1><p>Ready</p></body></html>")
            return

        if self.path == "/slow-first-byte":
            # Simulate delayed first byte (1.2s delay before sending headers)
            time.sleep(1.2)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Slow TTFB</title></head><body><h1>Loaded after TTFB delay</h1></body></html>")
            return

        if self.path == "/hanging-background":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = (
                b"<html><head><title>Hanging Background</title></head><body>"
                b"<h1>Page Content</h1>"
                b"<script>fetch('/api/hang').catch(()=>{});</script>"
                b"</body></html>"
            )
            self.wfile.write(html)
            return

        if self.path == "/api/hang":
            # Hang for 15s to simulate long-poll or sleeping backend
            time.sleep(15.0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "finally"}')
            return

        if self.path == "/slow-font":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = (
                b"<html><head><title>Slow Font</title>"
                b"<style>"
                b"@font-face { font-family: 'SlowFont'; src: url('/fonts/slow.woff2'); font-display: block; }"
                b"body { font-family: 'SlowFont', sans-serif; }"
                b"</style></head><body><h1>Text styled with slow font</h1></body></html>"
            )
            self.wfile.write(html)
            return

        if self.path == "/fonts/slow.woff2":
            # Hang for 10s if font requests are not blocked
            time.sleep(10.0)
            self.send_response(200)
            self.send_header("Content-Type", "font/woff2")
            self.end_headers()
            self.wfile.write(b"fakefontdata")
            return

        if self.path == "/slow-api-page":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = (
                b"<html><head><title>Slow API Page</title></head><body>"
                b"<h1>Dashboard View</h1>"
                b"<script>fetch('/api/slow-backend').catch(()=>{});</script>"
                b"</body></html>"
            )
            self.wfile.write(html)
            return

        if self.path == "/api/slow-backend":
            time.sleep(3.0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data": "ready"}')
            return

        if self.path == "/render-waking":
            LatencyFixtureHandler.render_wake_counter += 1
            if LatencyFixtureHandler.render_wake_counter == 1:
                # First request: Render waking interstitial
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Server", "Render")
                self.send_header("x-render-origin-server", "Render")
                self.end_headers()
                self.wfile.write(b"<html><head><title>Waking up</title></head><body>Your free instance is waking up</body></html>")
            else:
                # Second request: Real app is awake
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><head><title>Render App Awake</title></head><body><h1>Welcome to real app</h1></body></html>")
            return

        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="module")
def fixture_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LatencyFixtureHandler)
    host, port = server.server_address
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"
    yield base_url
    server.shutdown()
    server.server_close()


@pytest.mark.asyncio
async def test_fixture_fast_page_load_phases(fixture_server, monkeypatch):
    """Fast page should commit, reach DCL, FCP, and settle in fraction of a second."""
    from app.engine.browser import session as session_module
    monkeypatch.setattr(session_module, "_is_safe_url", lambda url: True)

    phases = []
    session = BrowserSession(headless=True)
    try:
        await session.start()
        # Intercept font and media requests to optimize load
        await session.page.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ("font", "media") else route.continue_()
        )

        t0 = time.perf_counter()
        res = await session.navigate(
            f"{fixture_server}/fast",
            on_phase=lambda data: phases.append(data)
        )
        total_s = time.perf_counter() - t0

        assert res.get("commit", {}).get("status") == 200
        assert total_s < 3.0  # Fast page completes well under 3s

        phase_names = [p["phase"] for p in phases]
        assert "commit" in phase_names
        assert "domcontentloaded" in phase_names
        assert "first_contentful_paint" in phase_names
        assert "dom_settled" in phase_names

        # Fast page has zero pending requests
        pending = session.get_pending_requests()
        assert len(pending) == 0
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_fixture_slow_first_byte_measured(fixture_server, monkeypatch):
    """Page with delayed first byte measures commit status and duration accurately."""
    from app.engine.browser import session as session_module
    monkeypatch.setattr(session_module, "_is_safe_url", lambda url: True)

    phases = []
    session = BrowserSession(headless=True)
    try:
        await session.start()
        res = await session.navigate(
            f"{fixture_server}/slow-first-byte",
            on_phase=lambda data: phases.append(data)
        )
        assert res.get("commit", {}).get("status") == 200

        commit_meta = next(p for p in phases if p["phase"] == "commit")
        assert commit_meta["status"] == 200
        # First byte was delayed ~1.2s, so commit duration should be >= 1.0s
        assert commit_meta["elapsed_s"] >= 1.0
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_fixture_hanging_background_request_does_not_stall(fixture_server, monkeypatch):
    """Page whose background API never finishes does not stall settlement beyond cap."""
    from app.engine.browser import session as session_module
    monkeypatch.setattr(session_module, "_is_safe_url", lambda url: True)

    session = BrowserSession(headless=True)
    try:
        await session.start()
        res = await session.navigate(f"{fixture_server}/hanging-background")
        assert res.get("commit", {}).get("status") == 200

        # Confirm the background /api/hang request is detected in-flight
        pending = session.get_pending_requests()
        assert any("/api/hang" in r["url"] for r in pending)

        slowest = session.get_slowest_pending_host()
        assert slowest is not None
        host, age_s = slowest
        assert "127.0.0.1" in host
        assert age_s >= 0

        # Wait for settle must proceed with rendered content within cap (max 2.0s)
        waiter = ReadinessWaiter(probe=lambda: None)
        t_settle_start = time.perf_counter()
        settle_res = await waiter.wait_for_settle(
            session.page,
            max_wait_s=2.0,
            pending_checker=session.get_slowest_pending_host,
        )
        settle_duration = time.perf_counter() - t_settle_start
        # Settle wait capped at ~2.0s, does NOT hang for the 15s API timeout
        assert settle_duration < 3.5
        assert settle_res["pending_host"] is not None
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_fixture_slow_font_blocking_keeps_screenshot_fast(fixture_server, monkeypatch):
    """Blocking font requests and disabling animations prevents slow font from inflating screenshot latency."""
    from app.engine.browser import session as session_module
    monkeypatch.setattr(session_module, "_is_safe_url", lambda url: True)

    session = BrowserSession(headless=True)
    try:
        await session.start()
        # Abort font and media routes
        await session.page.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ("font", "media") else route.continue_()
        )

        await session.navigate(f"{fixture_server}/slow-font")

        # Screenshot with font blocked should be almost instantaneous (<0.5s), not 10s
        t_shot = time.perf_counter()
        shot_bytes = await session.screenshot(full_page=False, animations="disabled")
        shot_duration = time.perf_counter() - t_shot

        assert len(shot_bytes) > 0
        assert shot_duration < 1.0, f"Screenshot took {shot_duration}s which indicates font was not blocked"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_fixture_slow_api_names_pending_host(fixture_server, monkeypatch):
    """Page slow due to pending backend API produces a message naming the host and age."""
    from app.engine.browser import session as session_module
    monkeypatch.setattr(session_module, "_is_safe_url", lambda url: True)

    session = BrowserSession(headless=True)
    try:
        await session.start()
        await session.navigate(f"{fixture_server}/slow-api-page")

        # Let the fetch start
        await asyncio.sleep(0.3)

        slowest = session.get_slowest_pending_host()
        assert slowest is not None
        host, age_s = slowest
        assert "127.0.0.1" in host
        assert age_s >= 0.2

        waiter = ReadinessWaiter(probe=lambda: None)
        settle_res = await waiter.wait_for_settle(
            session.page,
            max_wait_s=1.5,
            pending_checker=session.get_slowest_pending_host,
        )

        assert settle_res["pending_host"] is not None
        pending_msg = f"Page loaded; waiting on {settle_res['pending_host']} (pending {int(settle_res.get('pending_age_s', 0))}s)"
        assert "Page loaded; waiting on 127.0.0.1" in pending_msg
        assert "pending" in pending_msg
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_fixture_render_platform_wake_signature(fixture_server, monkeypatch):
    """Render wake interstitial is matched deterministically by signature and not by timer."""
    import httpx

    LatencyFixtureHandler.render_wake_counter = 0

    async with httpx.AsyncClient() as client:
        # First request receives Render interstitial
        resp1 = await client.get(f"{fixture_server}/render-waking")
        sig1 = detect_platform_wake(
            dict(resp1.headers),
            resp1.status_code,
            "Waking up",
            resp1.text,
            f"{fixture_server}/render-waking",
        )
        assert sig1.matched is True
        assert sig1.is_waking is True
        assert sig1.platform == "Render"
        assert "The hosting service (Render) is waking up" in sig1.message

        # Second request receives awake app
        resp2 = await client.get(f"{fixture_server}/render-waking")
        sig2 = detect_platform_wake(
            dict(resp2.headers),
            resp2.status_code,
            "Render App Awake",
            resp2.text,
            f"{fixture_server}/render-waking",
        )
        assert sig2.matched is False
        assert sig2.is_waking is False


@pytest.mark.asyncio
async def test_no_time_only_messages_emitted(fixture_server, monkeypatch):
    """Zero time-based guess messages ('Free-tier servers...', 'Site is slow or unreachable') are emitted."""
    from app.engine.exploration.explorer import ExplorationEngine
    import uuid

    emitted_messages = []
    async def event_collector(event_type: str, payload: dict):
        if "message" in payload:
            emitted_messages.append(payload["message"])

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url=f"{fixture_server}/fast",
        event_emitter=event_collector,
    )

    # Run warmup preflight against fast page
    result = await engine._warmup_preflight(f"{fixture_server}/fast")
    assert result["success"] is True

    # Confirm none of the old timer-based guess messages appear
    for msg in emitted_messages:
        assert "free-tier servers take around a minute" not in msg.lower()
        assert "site is slow or unreachable" not in msg.lower()
        assert "hosts like this can take up to a minute" not in msg.lower()
