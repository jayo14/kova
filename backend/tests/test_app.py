"""Deterministic test application for Kova browser automation.

Two-route app with server-side sessions:
  GET/POST /login  — login form, validates credentials, sets session
  GET /dashboard   — shows welcome if authenticated, else redirects to /login
  GET /health      — health check

Credentials are hardcoded for deterministics:
  email: test@kova.local
  password: KovaTest123!
"""

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer

app = FastAPI(title="Kova Test App")

SECRET_KEY = "kova-test-secret-key-do-not-use-in-production"
serializer = URLSafeTimedSerializer(SECRET_KEY)

TEST_EMAIL = "test@kova.local"
TEST_PASSWORD = "KovaTest123!"


def _set_session(response: Response, email: str) -> None:
    """Set a signed session cookie."""
    token = serializer.dumps({"email": email})
    response.set_cookie("session", token, httponly=True, max_age=3600)


def _get_session(request: Request) -> dict | None:
    """Validate and decode the session cookie. Returns None if invalid."""
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=3600)
    except Exception:
        return None


ROOT_PAGE = """<!DOCTYPE html>
<html>
<head><title>Kova Test App</title></head>
<body>
    <h1 id="welcome">Welcome to Kova Test</h1>
    <form id="login-form">
        <input type="text" id="username" name="username" placeholder="Username" />
        <input type="password" id="password" name="password" placeholder="Password" />
        <button type="submit" id="login-btn">Login</button>
    </form>
    <div id="result" style="display:none;">Login successful!</div>
</body>
<script>
document.getElementById('login-form').addEventListener('submit', function(e) {
    e.preventDefault();
    var user = document.getElementById('username').value;
    var pass = document.getElementById('password').value;
    if (user === 'admin' && pass === 'secret') {
        document.getElementById('result').style.display = 'block';
        document.getElementById('welcome').textContent = 'Hello, admin!';
    }
});
</script>
</html>"""

LOGIN_PAGE = """<!DOCTYPE html>
<html>
<head><title>Login</title></head>
<body>
    <h1>Login</h1>
    <form id="login-form" method="post" action="/login">
        <label for="email">Email</label>
        <input type="email" id="email" name="email" required />
        <label for="password">Password</label>
        <input type="password" id="password" name="password" required />
        <button type="submit" id="login-btn">Sign in</button>
    </form>
</body>
</html>"""

DASHBOARD_PAGE = """<!DOCTYPE html>
<html>
<head><title>Dashboard</title></head>
<body>
    <h1>Welcome, Kova</h1>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return ROOT_PAGE


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return LOGIN_PAGE


@app.post("/login")
async def login_submit(
    email: str = Form(""),
    password: str = Form(""),
):
    if email == TEST_EMAIL and password in (TEST_PASSWORD, "secret"):
        token = serializer.dumps({"email": email})
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie("session", token, httponly=True, max_age=3600)
        return response
    return Response(content="Invalid credentials", status_code=401)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    session = _get_session(request)
    if session is None:
        return RedirectResponse(url="/login", status_code=307)
    return DASHBOARD_PAGE


# ── Journey fixture routes (readiness spec §29) ─────────────────────

SEARCH_PAGE = """<!DOCTYPE html>
<html>
<head><title>Search</title></head>
<body>
    <main>
        <h1>Library Search</h1>
        <form id="search-form" method="get" action="/search">
            <input type="search" id="q" name="q" placeholder="Search resources" />
            <button type="submit" id="search-btn">Search</button>
        </form>
        <div id="results"></div>
    </main>
    <script>
        const params = new URLSearchParams(window.location.search);
        const q = params.get('q');
        const results = document.getElementById('results');
        const CATALOG = {
            'course': ['Biology 101', 'History of Art', 'Intro to Physics'],
            'zzznothing': []
        };
        if (q !== null) {
            const items = CATALOG[q.toLowerCase()] || CATALOG['course'];
            if (q.toLowerCase() === 'zzznothing') items.length = 0;
            if (items.length === 0) {
                results.innerHTML = '<p id="no-results">No results found for your search.</p>';
            } else {
                results.innerHTML = items.map(t =>
                    '<a class="result" href="/resource/' + encodeURIComponent(t) + '">' + t + '</a>'
                ).join('');
            }
        }
    </script>
</body>
</html>"""

LIBRARY_PAGE = """<!DOCTYPE html>
<html>
<head><title>Library</title></head>
<body>
    <main>
        <h1>Study Library</h1>
        <a class="resource" href="/resource/Biology%20101">Biology 101</a>
        <a class="resource" href="/resource/History%20of%20Art">History of Art</a>
        <a class="resource" href="/resource/Intro%20to%20Physics">Intro to Physics</a>
    </main>
</body>
</html>"""


def _resource_page(name: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><title>{name}</title></head>
<body>
    <main>
        <h1>{name}</h1>
        <p id="resource-content">Study material for {name}. Chapter one begins here.</p>
    </main>
</body>
</html>"""


CONTACT_PAGE = """<!DOCTYPE html>
<html>
<head><title>Contact</title></head>
<body>
    <main>
        <h1>Contact Us</h1>
        <form id="contact-form" method="post" action="/contact">
            <input type="text" id="name" name="name" placeholder="Your name" />
            <input type="email" id="email" name="email" placeholder="Your email" />
            <textarea id="message" name="message" placeholder="Message"></textarea>
            <button type="submit" id="contact-submit">Send</button>
        </form>
    </main>
</body>
</html>"""


# Scenario F — false success trap: the button clicks fine but the intended
# result (payment confirmation) NEVER appears. Verification must fail.
BROKEN_FLOW_PAGE = """<!DOCTYPE html>
<html>
<head><title>Checkout</title></head>
<body>
    <main>
        <h1>Checkout</h1>
        <button id="pay-btn" onclick="this.textContent='Clicked'">Pay now</button>
        <!-- intentionally NO confirmation element ever renders -->
    </main>
</body>
</html>"""


@app.get("/search", response_class=HTMLResponse)
async def search_page():
    return SEARCH_PAGE


@app.get("/library", response_class=HTMLResponse)
async def library_page():
    return LIBRARY_PAGE


@app.get("/resource/{name}", response_class=HTMLResponse)
async def resource_page(name: str):
    return _resource_page(name)


@app.get("/contact", response_class=HTMLResponse)
async def contact_page():
    return CONTACT_PAGE


@app.post("/contact")
async def contact_submit(name: str = Form(""), email: str = Form(""), message: str = Form("")):
    if name and email and message:
        return Response(content="<h1>Thanks!</h1><p id='sent'>Message sent successfully.</p>", status_code=200)
    return Response(content=CONTACT_PAGE, status_code=400)


@app.get("/checkout", response_class=HTMLResponse)
async def checkout_page():
    return BROKEN_FLOW_PAGE


@app.get("/health")
async def health():
    return {"status": "ok"}
