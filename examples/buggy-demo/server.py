#!/usr/bin/env python3
"""Buggy Demo App for Kova.

Planted Bugs:
1. Contact Form: UI reports success ("Thank you! Your message has been sent."),
   but POST /api/contact returns HTTP 500 Internal Server Error.
2. Login Flow: Submitting login credentials fails to authenticate and leaves the
   user stranded on the login page with the password input still present.
"""

import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
import sys
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8090

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Buggy Demo App</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }
    h1 { color: #111; }
    nav a { margin-right: 15px; color: #2563eb; text-decoration: none; font-weight: 500; }
    nav a:hover { text-decoration: underline; }
    .card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-top: 20px; }
  </style>
</head>
<body>
  <h1>Buggy Demo Application</h1>
  <p>This application contains two intentional bugs for Kova testing:</p>
  <ul>
    <li><strong>Bug 1 (Network Error)</strong>: Contact form reports success in UI, but the background API fails with HTTP 500.</li>
    <li><strong>Bug 2 (Authentication Error)</strong>: Login flow stays stuck on the login page and fails verification.</li>
  </ul>
  <nav>
    <a href="/contact">Contact Form (Bug 1)</a>
    <a href="/login">User Login (Bug 2)</a>
    <a href="/signup">Sign Up</a>
  </nav>
</body>
</html>
"""

CONTACT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Contact Us - Buggy Demo</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }
    label { display: block; margin-top: 15px; font-weight: 500; }
    input, textarea { width: 100%; padding: 8px 12px; margin-top: 5px; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; }
    button { margin-top: 20px; padding: 10px 20px; background: #2563eb; color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }
    .success { background: #dcfce7; border: 1px solid #86efac; color: #166534; padding: 12px; border-radius: 6px; margin-top: 20px; }
  </style>
</head>
<body>
  <h1>Contact Support</h1>
  <form id="contactForm">
    <label>Name
      <input type="text" name="name" required placeholder="Your name">
    </label>
    <label>Email
      <input type="email" name="email" required placeholder="you@example.com">
    </label>
    <label>Message
      <textarea name="message" rows="4" required placeholder="How can we help?"></textarea>
    </label>
    <button type="submit">Submit</button>
  </form>
  <div id="result"></div>
  <script>
    document.getElementById('contactForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      try {
        await fetch('/api/contact', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            name: this.name.value,
            email: this.email.value,
            message: this.message.value
          })
        });
      } catch (err) {
        // Ignored by UI bug
      }
      // Buggy UI: always displays success message even though API returned HTTP 500
      document.getElementById('result').innerHTML = '<div class="success">Thank you! Your message has been sent.</div>';
    });
  </script>
</body>
</html>
"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Login - Buggy Demo</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 400px; margin: 60px auto; padding: 0 20px; line-height: 1.6; }
    label { display: block; margin-top: 15px; font-weight: 500; }
    input { width: 100%; padding: 8px 12px; margin-top: 5px; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; }
    button { margin-top: 20px; width: 100%; padding: 10px 20px; background: #2563eb; color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }
    .error { background: #fee2e2; border: 1px solid #fca5a5; color: #991b1b; padding: 12px; border-radius: 6px; margin-top: 20px; }
  </style>
</head>
<body>
  <h1>User Login</h1>
  <form id="loginForm" method="POST" action="/login">
    <label>Email
      <input type="email" name="email" required placeholder="you@example.com">
    </label>
    <label>Password
      <input type="password" name="password" required placeholder="Password">
    </label>
    <button type="submit">Log in</button>
  </form>
  <div id="errorBox"></div>
  <script>
    if (window.location.search.includes('error=')) {
      document.getElementById('errorBox').innerHTML = '<div class="error">Authentication failed: Database unreachable.</div>';
    }
  </script>
</body>
</html>
"""

SIGNUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Sign Up - Buggy Demo</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 400px; margin: 60px auto; padding: 0 20px; line-height: 1.6; }
    label { display: block; margin-top: 15px; font-weight: 500; }
    input { width: 100%; padding: 8px 12px; margin-top: 5px; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; }
    button { margin-top: 20px; width: 100%; padding: 10px 20px; background: #2563eb; color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }
  </style>
</head>
<body>
  <h1>Create Account</h1>
  <form id="signupForm" method="POST" action="/signup">
    <label>Email
      <input type="email" name="email" required placeholder="you@example.com">
    </label>
    <label>Password
      <input type="password" name="password" required placeholder="Password">
    </label>
    <button type="submit">Sign up</button>
  </form>
</body>
</html>
"""

class BuggyDemoHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._send_html(INDEX_HTML)
        elif path == "/contact":
            self._send_html(CONTACT_HTML)
        elif path == "/login":
            self._send_html(LOGIN_HTML)
        elif path == "/signup":
            self._send_html(SIGNUP_HTML)
        elif path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self.send_error(404, "Page Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/contact":
            # Planted Bug 1: API returns 500 Internal Server Error
            self._send_json(500, {
                "status": "error",
                "message": "Internal Server Error: Mail delivery gateway failed to connect"
            })
        elif path in ("/login", "/api/login"):
            # Planted Bug 2: Redirect back to /login?error=auth_failed or return error
            # Leaving the user stuck on the login page with password field present
            self.send_response(303)
            self.send_header("Location", "/login?error=auth_failed")
            self.end_headers()
        elif path == "/signup":
            self.send_response(303)
            self.send_header("Location", "/login")
            self.end_headers()
        else:
            self.send_error(404, "Not Found")

    def _send_html(self, content: str, status: int = 200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress noisy logs in test environments unless debug requested
        pass


def run(host=HOST, port=PORT):
    server = HTTPServer((host, port), BuggyDemoHandler)
    print(f"Buggy Demo App listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run(port=port)
