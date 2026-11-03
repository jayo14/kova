"""Tests for slow first byte cold-start handling, platform identification, and target classification.

Verifies:
1. Platform identification from hostnames (*.onrender.com) and headers (rndr-id, x-render-origin-server).
2. The slow first byte model:
   - "Waiting for the server to respond (Ns)" emitted while headers are in-flight.
   - "The server took Ns to respond." with labeled inference "(Typical of a sleeping instance waking up.)"
     if on a sleeping platform, and no cause claimed otherwise.
3. Fixture holding response 5s then answering.
4. Fixture returning 404 at root with Django-style debug body: exploration halts with
   "This URL returned 404 at the root and looks like a backend or error page".
5. Fixture returning a real app after a held response: exploration proceeds normally.
"""

from __future__ import annotations

import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from app.engine.browser.platform_wake import (
    classify_target_document,
    format_slow_first_byte_message,
    identify_platform,
    is_sleeping_free_instance_platform,
)
from app.engine.exploration.explorer import ExplorationEngine


def test_real_render_capture_headers_file_exists():
    capture_path = Path("backend/tests/fixtures/platform_captures/render_cold_first_byte.txt")
    assert capture_path.exists(), f"Capture file not found at {capture_path}"
    content = capture_path.read_text()
    assert "# REAL" in content
    assert "log2def.onrender.com" in content
    assert "HTTP/1.1 404" in content
    assert "x-render-origin-server: gunicorn" in content.lower()
    assert "rndr-id:" in content.lower()


def test_platform_identification_hostname_and_headers():
    # 1. Before headers: hostname check
    assert identify_platform("https://my-app.onrender.com") == "Render"
    assert identify_platform("https://my-app.herokuapp.com") == "Heroku"
    assert identify_platform("https://my-app.railway.app") == "Railway"
    assert identify_platform("https://my-app.fly.dev") == "Fly.io"
    assert identify_platform("https://my-app.example.com") is None

    # 2. After headers: header check (even with custom domain)
    render_headers = {
        "server": "cloudflare",
        "rndr-id": "019a3b8c-5f21-71e8-9bc4-3b2d1f4a9c8e",
        "x-render-origin-server": "gunicorn",
    }
    assert identify_platform("https://app.customdomain.org", render_headers) == "Render"

    heroku_headers = {"via": "1.1 vegur", "x-heroku-queue-wait-time": "15ms"}
    assert identify_platform("https://app.customdomain.org", heroku_headers) == "Heroku"

    railway_headers = {"server": "railway", "x-railway-request-id": "req_123"}
    assert identify_platform("https://app.customdomain.org", railway_headers) == "Railway"


def test_slow_first_byte_formatting_no_cause_claimed_vs_labeled_inference():
    # Normal server late response (>20s): no cause claimed
    msg_custom = format_slow_first_byte_message(25.4, platform=None, threshold_s=20.0)
    assert msg_custom == "The server took 25s to respond."
    assert "Typical" not in msg_custom

    # Server on sleeping free platform (Render, Heroku, etc.): labeled inference (likely, never fact)
    msg_render = format_slow_first_byte_message(72.1, platform="Render", threshold_s=20.0)
    assert msg_render == "The server took 72s to respond. (Typical of a sleeping instance waking up.)"
    assert is_sleeping_free_instance_platform("Render") is True

    # Fast response (<20s): simple response time
    msg_fast = format_slow_first_byte_message(2.5, platform="Render", threshold_s=20.0)
    assert msg_fast == "The server responded in 2s."


def test_classify_target_document_django_debug_and_404():
    django_debug_body = """
    <!DOCTYPE html>
    <html lang="en">
    <head><title>Page not found (404)</title></head>
    <body>
    <h1>Page not found (404)</h1>
    <p>Using the URLconf defined in <code>config.urls</code>, Django tried these URL patterns, in this order:</p>
    <ol>
        <li>admin/</li>
        <li>api/v1/</li>
    </ol>
    <p>The empty path didn't match any of these.</p>
    <p>You're seeing this error because you have DEBUG = True in your Django settings file.</p>
    <div id="explanation"><p>Django Version: 5.1.2</p></div>
    </body>
    </html>
    """
    headers = {"content-type": "text/html; charset=utf-8", "server": "gunicorn"}
    is_backend, err_msg = classify_target_document(404, headers, django_debug_body, "Page not found (404)")
    assert is_backend is True
    assert "This URL returned 404 at the root and looks like a backend or error page" in err_msg


def test_classify_target_document_json_body_and_bare_server_errors():
    # JSON API at root
    json_body = '{"detail": "Not Found", "status": 404}'
    is_backend, err_msg = classify_target_document(404, {"content-type": "application/json"}, json_body, "")
    assert is_backend is True
    assert "This URL returned 404 at the root and looks like a backend or error page" in err_msg

    # Bare nginx error
    nginx_body = "<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>nginx/1.18.0</center></body></html>"
    is_backend2, err_msg2 = classify_target_document(502, {"server": "nginx"}, nginx_body, "502 Bad Gateway")
    assert is_backend2 is True
    assert "This URL returned 502 at the root and looks like a backend or error page" in err_msg2

    # Normal application HTML
    app_html = "<html><head><title>Acme App</title></head><body><header><nav><a href='/features'>Features</a></nav></header><main><h1>Welcome</h1></main></body></html>"
    is_backend3, _ = classify_target_document(200, {"content-type": "text/html"}, app_html, "Acme App")
    assert is_backend3 is False


def test_classify_target_document_bot_challenge_and_auth_required():
    # 1. Cloudflare "Just a moment..." page
    cf_body = "<html><head><title>Just a moment...</title></head><body>Enable JavaScript and cookies to continue. Cloudflare Ray ID: 890123</body></html>"
    cf_res = classify_target_document(403, {"server": "cloudflare", "cf-ray": "890123"}, cf_body, "Just a moment...")
    assert cf_res.is_invalid is True
    assert cf_res.error_code == "BOT_BLOCKED"
    assert "Bot verification challenge detected" in cf_res.message
    assert "backend or error page" not in cf_res.message
    assert cf_res.can_continue is False

    # 2. Turnstile challenge
    turnstile_body = "<html><head><title>Security Check</title></head><body><div class='cf-turnstile' data-sitekey='xxx'></div>Please verify you are human</body></html>"
    ts_res = classify_target_document(200, {}, turnstile_body, "Security Check")
    assert ts_res.is_invalid is True
    assert ts_res.error_code == "BOT_BLOCKED"
    assert ts_res.can_continue is False

    # 3. HTTP 401 Unauthorized
    auth_401 = classify_target_document(401, {}, "Unauthorized", "401 Unauthorized")
    assert auth_401.is_invalid is True
    assert auth_401.error_code == "AUTH_REQUIRED"
    assert "Authentication Required" in auth_401.message
    assert "backend or error page" not in auth_401.message
    assert auth_401.can_continue is False

    # 4. HTTP 403 Forbidden without bot tokens
    auth_403 = classify_target_document(403, {}, "Forbidden: Access is denied", "Forbidden")
    assert auth_403.is_invalid is True
    assert auth_403.error_code == "AUTH_REQUIRED"
    assert "backend or error page" not in auth_403.message
    assert auth_403.can_continue is False

    # 5. Root 404 is INVALID_TARGET with can_continue=True
    err_404 = classify_target_document(404, {}, "Not Found", "404 Not Found")
    assert err_404.is_invalid is True
    assert err_404.error_code == "INVALID_TARGET"
    assert err_404.can_continue is True


@pytest.mark.asyncio
async def test_invalid_target_continue_anyway_option(slow_test_server):
    target_url = f"{slow_test_server}/django-debug-404"

    # Default: allow_invalid_target is False -> returns INVALID_TARGET with can_continue=True and option
    explorer_default = ExplorationEngine(url=target_url, exploration_id="test_opt1")
    res1 = await explorer_default._warmup_preflight(target_url)
    assert res1["success"] is False
    assert res1["error_code"] == "INVALID_TARGET"
    assert res1["can_continue"] is True
    assert res1["options"] == [{"id": "continue_anyway", "label": "Continue anyway"}]

    # When allow_invalid_target=True -> proceeds despite INVALID_TARGET
    explorer_allowed = ExplorationEngine(url=target_url, exploration_id="test_opt2", allow_invalid_target=True)
    res2 = await explorer_allowed._warmup_preflight(target_url)
    assert res2["success"] is True


class MockSlowServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/slow-held":
            # Hold response for 3 seconds to test in-flight heartbeat and response
            time.sleep(3.0)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<!DOCTYPE html><html><head><title>App Ready</title></head><body><h1>Welcome</h1></body></html>")
        elif self.path == "/django-debug-404":
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Server", "gunicorn")
            self.end_headers()
            body = (
                "<html><head><title>Page not found</title></head><body>"
                "<h1>Page not found (404)</h1>"
                "<p>Using the URLconf defined in project.urls, Django tried these URL patterns:</p>"
                "<p>The empty path didn't match any of these.</p>"
                "<p>You're seeing this error because you have DEBUG = True.</p>"
                "</body></html>"
            )
            self.wfile.write(body.encode("utf-8"))
        elif self.path == "/real-app-after-held":
            # Real application response after 1.5s delay
            time.sleep(1.5)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            app_body = (
                "<!DOCTYPE html><html><head><title>Live Dashboard</title></head>"
                "<body><nav><a href='/home'>Home</a><a href='/reports'>Reports</a></nav>"
                "<h1>Application Dashboard</h1><button id='start-btn'>Start</button></body></html>"
            )
            self.wfile.write(app_body.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def slow_test_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockSlowServerHandler)
    host, port = server.server_address
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}"
    server.shutdown()


@pytest.mark.asyncio
async def test_preflight_held_response_emits_waiting_heartbeats_and_completes(slow_test_server):
    target_url = f"{slow_test_server}/slow-held"
    explorer = ExplorationEngine(url=target_url, exploration_id="test_held")

    emitted_progress = []

    async def _mock_emit(event_type, payload):
        if event_type == "progress":
            emitted_progress.append(payload)

    explorer._emit = _mock_emit

    res = await explorer._warmup_preflight(target_url)
    assert res["success"] is True
    assert res["status_code"] == 200
    assert res["ttfb_seconds"] >= 2.5

    # Verify at least one in-flight heartbeat was emitted stating "Waiting for the server to respond"
    waiting_msgs = [p["message"] for p in emitted_progress if "Waiting for the server to respond" in p.get("message", "")]
    assert len(waiting_msgs) >= 1
    # Check that no speculation was emitted in the waiting messages
    assert all("wake" not in m.lower() for m in waiting_msgs)


@pytest.mark.asyncio
async def test_django_debug_404_root_halts_exploration_with_clear_message(slow_test_server):
    target_url = f"{slow_test_server}/django-debug-404"
    explorer = ExplorationEngine(url=target_url, exploration_id="test_django_404")

    emitted_events = []

    async def _mock_emit(event_type, payload):
        emitted_events.append((event_type, payload))

    explorer._emit = _mock_emit

    # Preflight should detect the backend/debug page and immediately fail with INVALID_TARGET
    res = await explorer._warmup_preflight(target_url)
    assert res["success"] is False
    assert res["error_code"] == "INVALID_TARGET"
    assert "This URL returned 404 at the root and looks like a backend or error page" in res["error"]


@pytest.mark.asyncio
async def test_real_app_after_held_response_proceeds_normally(slow_test_server):
    target_url = f"{slow_test_server}/real-app-after-held"
    explorer = ExplorationEngine(url=target_url, exploration_id="test_real_app")

    async def _mock_emit(event_type, payload):
        pass

    explorer._emit = _mock_emit

    res = await explorer._warmup_preflight(target_url)
    assert res["success"] is True
    assert res["status_code"] == 200
    assert res["ttfb_seconds"] >= 1.0
