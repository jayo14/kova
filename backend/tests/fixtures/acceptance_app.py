"""Controlled test application for Kova Phase 1.5 automated acceptance testing.

Provides deterministic workflows:
- Public landing page with working navigation
- Registration form with required fields and consent checkbox
- Login page and session handling
- Protected routes (dashboard, record creation, record listing)
- Form to create records with validation
- Records list page with search and filtering
- Client and server-side validation error scenarios
- Record persistence verified across browser refreshes
- Deterministic API state endpoints for programmatic verification
"""

import uuid
from typing import Any
from fastapi import FastAPI, Request, Response, Form, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

acceptance_app = FastAPI(title="Kova Controlled Acceptance App")

# ── In-Memory Deterministic State ─────────────────────────────────────

USERS: dict[str, dict[str, Any]] = {
    "testuser@kova.local": {
        "email": "testuser@kova.local",
        "name": "Test User",
        "password": "Password123!",
        "role": "user",
    },
    "admin@kova.local": {
        "email": "admin@kova.local",
        "name": "Admin User",
        "password": "AdminPassword123!",
        "role": "admin",
    },
}

SESSIONS: dict[str, str] = {}  # session_token -> email

DEFAULT_RECORDS: list[dict[str, Any]] = [
    {
        "id": "rec-101",
        "title": "Initial System Baseline",
        "category": "infrastructure",
        "priority": "high",
        "description": "Baseline deployment health verification",
        "owner": "testuser@kova.local",
        "created_at": "2026-10-25T12:00:00Z",
    },
    {
        "id": "rec-102",
        "title": "Payment Gateway Integration",
        "category": "feature",
        "priority": "medium",
        "description": "Stripe webhook handling and status sync",
        "owner": "testuser@kova.local",
        "created_at": "2026-10-25T13:00:00Z",
    },
    {
        "id": "rec-103",
        "title": "Flaky Locator Diagnostic",
        "category": "bug",
        "priority": "low",
        "description": "Investigate dynamic ID shifts on authentication forms",
        "owner": "admin@kova.local",
        "created_at": "2026-10-25T14:00:00Z",
    },
]

RECORDS: list[dict[str, Any]] = list(DEFAULT_RECORDS)


def reset_state():
    """Reset state for deterministic tests."""
    USERS.clear()
    USERS.update({
        "testuser@kova.local": {
            "email": "testuser@kova.local",
            "name": "Test User",
            "password": "Password123!",
            "role": "user",
        },
        "admin@kova.local": {
            "email": "admin@kova.local",
            "name": "Admin User",
            "password": "AdminPassword123!",
            "role": "admin",
        },
    })
    SESSIONS.clear()
    RECORDS.clear()
    RECORDS.extend(DEFAULT_RECORDS)


def get_current_user(request: Request) -> dict[str, Any] | None:
    session_id = request.cookies.get("session_id")
    if not session_id:
        # Also check Authorization header
        auth_hdr = request.headers.get("Authorization") or ""
        if auth_hdr.startswith("Bearer "):
            session_id = auth_hdr.split(" ")[1]
    if session_id and session_id in SESSIONS:
        email = SESSIONS[session_id]
        return USERS.get(email)
    return None


def _layout(title: str, content: str, user: dict[str, Any] | None = None) -> str:
    user_nav = (
        f"""<div class="user-info">
            <span id="user-greeting" class="user-greeting">Welcome, <strong id="user-name">{user['name']}</strong> ({user['role']})</span>
            <a href="/dashboard" id="nav-dashboard" class="nav-link">Dashboard</a>
            <a href="/records" id="nav-records" class="nav-link">Records</a>
            <a href="/records/new" id="nav-create-record" class="nav-link">Create Record</a>
            <a href="/logout" id="nav-logout" class="nav-link btn-logout">Log Out</a>
        </div>"""
        if user
        else """<div class="auth-nav">
            <a href="/login" id="nav-login" class="nav-link">Sign In</a>
            <a href="/register" id="nav-register" class="nav-link btn-primary">Get Started / Register</a>
        </div>"""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Kova Controlled App</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --border: #475569;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --danger: #ef4444;
            --success: #10b981;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        header {{
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .brand {{
            font-weight: 700;
            font-size: 1.25rem;
            color: var(--text);
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        nav {{ display: flex; gap: 1rem; align-items: center; }}
        .nav-link {{
            color: var(--text-muted);
            text-decoration: none;
            font-size: 0.95rem;
            padding: 0.4rem 0.8rem;
            border-radius: 4px;
            transition: all 0.2s;
        }}
        .nav-link:hover {{ color: var(--text); background: var(--surface-hover); }}
        .btn-primary {{
            background: var(--primary);
            color: white !important;
            font-weight: 500;
        }}
        .btn-primary:hover {{ background: var(--primary-hover); }}
        .btn-logout {{ color: var(--danger) !important; }}
        main {{
            flex: 1;
            padding: 2rem;
            max-width: 1000px;
            margin: 0 auto;
            width: 100%;
        }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.75rem;
            margin-bottom: 1.5rem;
        }}
        h1, h2, h3 {{ color: var(--text); margin-bottom: 1rem; }}
        p {{ color: var(--text-muted); margin-bottom: 1rem; }}
        .form-group {{ margin-bottom: 1.25rem; }}
        label {{ display: block; margin-bottom: 0.5rem; font-weight: 500; color: var(--text); }}
        input[type="text"], input[type="email"], input[type="password"], select, textarea {{
            width: 100%;
            padding: 0.65rem 0.85rem;
            background: #0b1120;
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text);
            font-size: 1rem;
        }}
        input:focus, select:focus, textarea:focus {{
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
        }}
        .checkbox-group {{ display: flex; align-items: flex-start; gap: 0.5rem; }}
        .checkbox-group input {{ margin-top: 0.3rem; }}
        button, input[type="submit"] {{
            padding: 0.65rem 1.25rem;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }}
        button:hover, input[type="submit"]:hover {{ background: var(--primary-hover); }}
        .alert {{
            padding: 0.85rem 1rem;
            border-radius: 6px;
            margin-bottom: 1.25rem;
            font-size: 0.95rem;
        }}
        .alert-danger {{
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid var(--danger);
            color: #fca5a5;
        }}
        .alert-success {{
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid var(--success);
            color: #6ee7b7;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }}
        th, td {{
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{ background: #131d31; color: var(--text-muted); font-size: 0.85rem; text-transform: uppercase; }}
        tr:hover {{ background: var(--surface-hover); }}
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .badge-high {{ background: rgba(239, 68, 68, 0.2); color: #f87171; }}
        .badge-medium {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; }}
        .badge-low {{ background: rgba(16, 185, 129, 0.2); color: #34d399; }}
        .search-bar {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }}
        .search-bar input {{ flex: 2; min-width: 200px; }}
        .search-bar select {{ flex: 1; min-width: 140px; }}
        .search-bar button {{ flex: 0 0 auto; }}
        footer {{
            background: var(--surface);
            border-top: 1px solid var(--border);
            padding: 1.5rem;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.85rem;
        }}
    </style>
</head>
<body>
    <header>
        <a href="/" class="brand">
            <span>⚡</span>
            <span>Kova Acceptance App</span>
        </a>
        <nav id="main-nav">
            <a href="/" id="nav-home" class="nav-link">Home</a>
            <a href="/about" id="nav-about" class="nav-link">About</a>
            {user_nav}
        </nav>
    </header>
    <main role="main">
        {content}
    </main>
    <footer>
        <p>Kova QA Automation Acceptance Test Bed &bull; Fully Local Deterministic Verification</p>
    </footer>
</body>
</html>"""


# ── Public Landing Page ───────────────────────────────────────────────


@acceptance_app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    user = get_current_user(request)
    content = f"""
    <div class="card" id="landing-hero">
        <h1>Welcome to the Kova Acceptance Application</h1>
        <p>A controlled, deterministic web application built to verify Kova's autonomous discovery, registration, authentication, record management, search, filtering, and state persistence.</p>
        <div style="display: flex; gap: 1rem; margin-top: 1.5rem;">
            {f'<a href="/dashboard" id="hero-dashboard-btn"><button>Go to Dashboard</button></a>' if user else '<a href="/register" id="hero-register-btn"><button>Create an Account</button></a> <a href="/login" id="hero-login-btn"><button style="background: var(--surface-hover); border: 1px solid var(--border);">Sign In</button></a>'}
        </div>
    </div>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.5rem;">
        <div class="card">
            <h3>🔐 Authentication &amp; Roles</h3>
            <p>Self-service registration with required consent validation and role-based permissions.</p>
        </div>
        <div class="card">
            <h3>📝 Record Management</h3>
            <p>Create, inspect, and persist critical test records backed by session state.</p>
        </div>
        <div class="card">
            <h3>🔍 Search &amp; Filter</h3>
            <p>Interactive full-text search and category filtering with deterministic result sets.</p>
        </div>
    </div>
    """
    return HTMLResponse(content=_layout("Home", content, user))


@acceptance_app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    user = get_current_user(request)
    content = """
    <div class="card">
        <h1>About This Application</h1>
        <p>This application serves as the independent verification benchmark for Kova Phase 1.5. It does not rely on third-party APIs and behaves deterministically across runs.</p>
    </div>
    """
    return HTMLResponse(content=_layout("About", content, user))


# ── Registration Page & Submission ────────────────────────────────────


@acceptance_app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str | None = None):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)

    error_html = (
        f'<div role="alert" id="register-error" class="alert alert-danger error-message">{error}</div>'
        if error
        else ""
    )

    content = f"""
    <div class="card" style="max-width: 500px; margin: 2rem auto;">
        <h2>Create an Account</h2>
        <p>Register a disposable test account to explore authenticated features.</p>
        {error_html}
        <form id="registration-form" method="POST" action="/register">
            <div class="form-group">
                <label for="name">Full Name</label>
                <input type="text" id="name" name="name" placeholder="Alex Morgan" required />
            </div>
            <div class="form-group">
                <label for="email">Work Email</label>
                <input type="email" id="email" name="email" placeholder="alex@kova.local" required />
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="••••••••••••" required />
            </div>
            <div class="form-group">
                <label for="role">Requested Role</label>
                <select id="role" name="role">
                    <option value="user" selected>User</option>
                    <option value="manager">Manager</option>
                    <option value="admin">Administrator</option>
                </select>
            </div>
            <div class="form-group checkbox-group">
                <input type="checkbox" id="terms_consent" name="terms_consent" value="agreed" />
                <label for="terms_consent">I agree to the Terms of Service and Privacy Policy</label>
            </div>
            <div class="form-group" style="margin-top: 1.5rem;">
                <button type="submit" id="btn-submit-register" style="width: 100%;">Complete Registration</button>
            </div>
        </form>
        <p style="text-align: center; font-size: 0.9rem; margin-top: 1rem;">
            Already have an account? <a href="/login" id="link-to-login">Sign In</a>
        </p>
    </div>
    """
    return HTMLResponse(content=_layout("Register", content, user))


@acceptance_app.post("/register")
async def register_submit(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    terms_consent: str | None = Form(None),
):
    email = email.strip().lower()
    name = name.strip()

    # Validation: consent checkbox
    if terms_consent != "agreed":
        return HTMLResponse(
            status_code=422,
            content=_layout(
                "Register",
                f"""
                <div class="card" style="max-width: 500px; margin: 2rem auto;">
                    <h2>Create an Account</h2>
                    <div role="alert" id="register-error" class="alert alert-danger error-message">
                        You must agree to the Terms of Service and Privacy Policy to register.
                    </div>
                    <form id="registration-form" method="POST" action="/register">
                        <div class="form-group">
                            <label for="name">Full Name</label>
                            <input type="text" id="name" name="name" value="{name}" required />
                        </div>
                        <div class="form-group">
                            <label for="email">Work Email</label>
                            <input type="email" id="email" name="email" value="{email}" required />
                        </div>
                        <div class="form-group">
                            <label for="password">Password</label>
                            <input type="password" id="password" name="password" required />
                        </div>
                        <div class="form-group">
                            <label for="role">Requested Role</label>
                            <select id="role" name="role">
                                <option value="user" {"selected" if role=="user" else ""}>User</option>
                                <option value="manager" {"selected" if role=="manager" else ""}>Manager</option>
                                <option value="admin" {"selected" if role=="admin" else ""}>Administrator</option>
                            </select>
                        </div>
                        <div class="form-group checkbox-group">
                            <input type="checkbox" id="terms_consent" name="terms_consent" value="agreed" />
                            <label for="terms_consent">I agree to the Terms of Service and Privacy Policy</label>
                        </div>
                        <div class="form-group" style="margin-top: 1.5rem;">
                            <button type="submit" id="btn-submit-register" style="width: 100%;">Complete Registration</button>
                        </div>
                    </form>
                </div>
                """,
            ),
        )

    # Validation: password length
    if len(password) < 6:
        return HTMLResponse(
            status_code=422,
            content=_layout(
                "Register",
                f"""
                <div class="card" style="max-width: 500px; margin: 2rem auto;">
                    <h2>Create an Account</h2>
                    <div role="alert" id="register-error" class="alert alert-danger error-message">
                        Password must be at least 6 characters long.
                    </div>
                    <form id="registration-form" method="POST" action="/register">
                        <div class="form-group">
                            <label for="name">Full Name</label>
                            <input type="text" id="name" name="name" value="{name}" required />
                        </div>
                        <div class="form-group">
                            <label for="email">Work Email</label>
                            <input type="email" id="email" name="email" value="{email}" required />
                        </div>
                        <div class="form-group">
                            <label for="password">Password</label>
                            <input type="password" id="password" name="password" required />
                        </div>
                        <div class="form-group checkbox-group">
                            <input type="checkbox" id="terms_consent" name="terms_consent" value="agreed" checked />
                            <label for="terms_consent">I agree to the Terms of Service and Privacy Policy</label>
                        </div>
                        <button type="submit" id="btn-submit-register">Complete Registration</button>
                    </form>
                </div>
                """,
            ),
        )

    # Duplicate account check
    if email in USERS:
        # Check if already registered
        return HTMLResponse(
            status_code=409,
            content=_layout(
                "Register",
                f"""
                <div class="card" style="max-width: 500px; margin: 2rem auto;">
                    <h2>Create an Account</h2>
                    <div role="alert" id="register-error" class="alert alert-danger error-message">
                        An account with email {email} already exists. Please sign in instead.
                    </div>
                    <p><a href="/login?email={email}" id="duplicate-login-link">Sign In with this email</a></p>
                </div>
                """,
            ),
        )

    # Register user
    USERS[email] = {
        "email": email,
        "name": name,
        "password": password,
        "role": role,
    }

    # Automatically create session and redirect to dashboard
    session_id = f"sess_{uuid.uuid4().hex}"
    SESSIONS[session_id] = email

    response = RedirectResponse(url="/dashboard?registered=1", status_code=303)
    response.set_cookie(key="session_id", value=session_id, httponly=True)
    return response


# ── Login Page & Submission ───────────────────────────────────────────


@acceptance_app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    email: str | None = None,
    error: str | None = None,
    registered: str | None = None,
):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)

    msg_html = ""
    if registered:
        msg_html = '<div role="status" class="alert alert-success">Registration successful! Please sign in.</div>'
    elif error:
        msg_html = f'<div role="alert" id="login-error" class="alert alert-danger error-message">{error}</div>'

    content = f"""
    <div class="card" style="max-width: 440px; margin: 2rem auto;">
        <h2>Sign In</h2>
        <p>Access your authenticated workspace.</p>
        {msg_html}
        <form id="login-form" method="POST" action="/login">
            <div class="form-group">
                <label for="login-email">Email or Username</label>
                <input type="text" id="login-email" name="email" value="{email or ''}" placeholder="testuser@kova.local" required />
            </div>
            <div class="form-group">
                <label for="login-password">Password</label>
                <input type="password" id="login-password" name="password" placeholder="••••••••••••" required />
            </div>
            <div class="form-group" style="margin-top: 1.5rem;">
                <button type="submit" id="btn-submit-login" style="width: 100%;">Sign In</button>
            </div>
        </form>
        <div style="margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: 0.85rem; color: var(--text-muted);">
            <p><strong>Demo Credentials:</strong></p>
            <p>User: <code>testuser@kova.local</code> / <code>Password123!</code></p>
            <p>Admin: <code>admin@kova.local</code> / <code>AdminPassword123!</code></p>
        </div>
    </div>
    """
    return HTMLResponse(content=_layout("Sign In", content, user))


@acceptance_app.post("/login")
async def login_submit(
    email: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    user = USERS.get(email)

    if not user or user["password"] != password:
        return HTMLResponse(
            status_code=401,
            content=_layout(
                "Sign In",
                f"""
                <div class="card" style="max-width: 440px; margin: 2rem auto;">
                    <h2>Sign In</h2>
                    <div role="alert" id="login-error" class="alert alert-danger error-message">
                        Invalid email or password.
                    </div>
                    <form id="login-form" method="POST" action="/login">
                        <div class="form-group">
                            <label for="login-email">Email or Username</label>
                            <input type="text" id="login-email" name="email" value="{email}" required />
                        </div>
                        <div class="form-group">
                            <label for="login-password">Password</label>
                            <input type="password" id="login-password" name="password" required />
                        </div>
                        <button type="submit" id="btn-submit-login" style="width: 100%;">Sign In</button>
                    </form>
                </div>
                """,
            ),
        )

    session_id = f"sess_{uuid.uuid4().hex}"
    SESSIONS[session_id] = email

    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="session_id", value=session_id, httponly=True)
    return response


@acceptance_app.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        SESSIONS.pop(session_id, None)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="session_id")
    return response


# ── Protected Dashboard Route ─────────────────────────────────────────


@acceptance_app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?error=Authentication+required", status_code=302)

    total_records = len(RECORDS)
    my_records = len([r for r in RECORDS if r.get("owner") == user["email"]])

    content = f"""
    <div class="card" id="dashboard-card">
        <h1>Workspace Dashboard</h1>
        <p id="dashboard-welcome">Authenticated as <strong id="current-user-email">{user['email']}</strong> with role <span class="badge badge-high">{user['role']}</span>.</p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 1.5rem 0;">
            <div style="background: #0b1120; padding: 1rem; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 0.85rem; color: var(--text-muted);">Total Records</div>
                <div style="font-size: 1.8rem; font-weight: 700;" id="metric-total-records">{total_records}</div>
            </div>
            <div style="background: #0b1120; padding: 1rem; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 0.85rem; color: var(--text-muted);">My Created Records</div>
                <div style="font-size: 1.8rem; font-weight: 700;" id="metric-my-records">{my_records}</div>
            </div>
            <div style="background: #0b1120; padding: 1rem; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 0.85rem; color: var(--text-muted);">System Status</div>
                <div style="font-size: 1.2rem; font-weight: 600; color: var(--success); margin-top: 0.3rem;" id="system-status">● Operational</div>
            </div>
        </div>
        <div style="display: flex; gap: 1rem;">
            <a href="/records/new" id="btn-quick-create"><button>+ Create Test Record</button></a>
            <a href="/records" id="btn-quick-view"><button style="background: var(--surface-hover); border: 1px solid var(--border);">View &amp; Search Records</button></a>
        </div>
    </div>
    """
    return HTMLResponse(content=_layout("Dashboard", content, user))


# ── Protected Record Creation Route ───────────────────────────────────


@acceptance_app.get("/records/new", response_class=HTMLResponse)
async def create_record_page(request: Request, error: str | None = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?error=Authentication+required", status_code=302)

    error_html = (
        f'<div role="alert" id="record-error" class="alert alert-danger error-message">{error}</div>'
        if error
        else ""
    )

    content = f"""
    <div class="card" style="max-width: 600px; margin: 1rem auto;">
        <h2>Create New Record</h2>
        <p>Submit a new structured test record into the application catalog.</p>
        {error_html}
        <form id="create-record-form" method="POST" action="/records/new">
            <div class="form-group">
                <label for="title">Record Title *</label>
                <input type="text" id="title" name="title" placeholder="e.g. User Authentication Flow Test" required />
            </div>
            <div class="form-group">
                <label for="category">Category</label>
                <select id="category" name="category">
                    <option value="feature" selected>Feature</option>
                    <option value="bug">Bug</option>
                    <option value="task">Task</option>
                    <option value="infrastructure">Infrastructure</option>
                </select>
            </div>
            <div class="form-group">
                <label for="priority">Priority</label>
                <select id="priority" name="priority">
                    <option value="low">Low</option>
                    <option value="medium" selected>Medium</option>
                    <option value="high">High</option>
                </select>
            </div>
            <div class="form-group">
                <label for="description">Detailed Description</label>
                <textarea id="description" name="description" rows="4" placeholder="Execution observations, expected outcomes, and acceptance conditions"></textarea>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 1.5rem;">
                <a href="/records" class="nav-link">Cancel</a>
                <button type="submit" id="btn-submit-record">Save Record</button>
            </div>
        </form>
    </div>
    """
    return HTMLResponse(content=_layout("Create Record", content, user))


@acceptance_app.post("/records/new")
async def create_record_submit(
    request: Request,
    title: str = Form(...),
    category: str = Form("feature"),
    priority: str = Form("medium"),
    description: str = Form(""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?error=Authentication+required", status_code=302)

    title = title.strip()
    if len(title) < 3:
        return HTMLResponse(
            status_code=422,
            content=_layout(
                "Create Record",
                f"""
                <div class="card" style="max-width: 600px; margin: 1rem auto;">
                    <h2>Create New Record</h2>
                    <div role="alert" id="record-error" class="alert alert-danger error-message">
                        Title must be at least 3 characters long.
                    </div>
                    <form id="create-record-form" method="POST" action="/records/new">
                        <div class="form-group">
                            <label for="title">Record Title *</label>
                            <input type="text" id="title" name="title" value="{title}" required />
                        </div>
                        <div class="form-group">
                            <label for="category">Category</label>
                            <select id="category" name="category">
                                <option value="feature" {"selected" if category=="feature" else ""}>Feature</option>
                                <option value="bug" {"selected" if category=="bug" else ""}>Bug</option>
                                <option value="task" {"selected" if category=="task" else ""}>Task</option>
                                <option value="infrastructure" {"selected" if category=="infrastructure" else ""}>Infrastructure</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="priority">Priority</label>
                            <select id="priority" name="priority">
                                <option value="low" {"selected" if priority=="low" else ""}>Low</option>
                                <option value="medium" {"selected" if priority=="medium" else ""}>Medium</option>
                                <option value="high" {"selected" if priority=="high" else ""}>High</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="description">Detailed Description</label>
                            <textarea id="description" name="description" rows="4">{description}</textarea>
                        </div>
                        <button type="submit" id="btn-submit-record">Save Record</button>
                    </form>
                </div>
                """,
                user,
            ),
        )

    new_id = f"rec-{uuid.uuid4().hex[:6]}"
    record = {
        "id": new_id,
        "title": title,
        "category": category,
        "priority": priority,
        "description": description.strip(),
        "owner": user["email"],
        "created_at": "2026-10-26T01:00:00Z",
    }
    RECORDS.append(record)

    return RedirectResponse(url=f"/records?created={new_id}", status_code=303)


# ── Protected Records Listing, Search & Filter ────────────────────────


@acceptance_app.get("/records", response_class=HTMLResponse)
async def list_records_page(
    request: Request,
    q: str = Query("", alias="q"),
    category: str = Query("all", alias="category"),
    created: str | None = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?error=Authentication+required", status_code=302)

    query = q.strip().lower()
    filtered = RECORDS

    if query:
        filtered = [
            r
            for r in filtered
            if query in r["title"].lower() or query in r.get("description", "").lower()
        ]

    if category and category != "all":
        filtered = [r for r in filtered if r.get("category", "").lower() == category.lower()]

    created_banner = ""
    if created:
        created_banner = f'<div role="status" id="creation-success" class="alert alert-success">Record {created} was successfully saved and persisted!</div>'

    rows_html = ""
    for r in filtered:
        p_class = f"badge-{r.get('priority', 'medium')}"
        rows_html += f"""
        <tr class="record-row" id="row-{r['id']}">
            <td><strong class="record-title">{r['title']}</strong><br><small style="color: var(--text-muted);">{r.get('description', '')}</small></td>
            <td><span class="badge" style="background: var(--surface-hover);">{r.get('category', 'general')}</span></td>
            <td><span class="badge {p_class}">{r.get('priority', 'medium')}</span></td>
            <td><small>{r.get('owner', '')}</small></td>
            <td><code>{r['id']}</code></td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="5" id="no-records-message" style="text-align: center; color: var(--text-muted); padding: 2rem;">No matching records found.</td></tr>'

    content = f"""
    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
            <h2>Record Catalog</h2>
            <a href="/records/new" id="btn-add-record"><button>+ New Record</button></a>
        </div>
        {created_banner}
        <form method="GET" action="/records" id="search-filter-form" class="search-bar">
            <input type="text" id="search-input" name="q" value="{q}" placeholder="Search records by title or description..." />
            <select id="category-filter" name="category">
                <option value="all" {"selected" if category=="all" else ""}>All Categories</option>
                <option value="feature" {"selected" if category=="feature" else ""}>Feature</option>
                <option value="bug" {"selected" if category=="bug" else ""}>Bug</option>
                <option value="task" {"selected" if category=="task" else ""}>Task</option>
                <option value="infrastructure" {"selected" if category=="infrastructure" else ""}>Infrastructure</option>
            </select>
            <button type="submit" id="btn-filter">Search &amp; Filter</button>
            <a href="/records" id="btn-reset-filters" class="nav-link" style="padding: 0.65rem 0.85rem; border: 1px solid var(--border); display: inline-flex; align-items: center;">Reset</a>
        </form>
        <div style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.5rem;" id="results-count">
            Showing <strong id="record-count">{len(filtered)}</strong> records
        </div>
        <table id="records-table">
            <thead>
                <tr>
                    <th>Title &amp; Description</th>
                    <th>Category</th>
                    <th>Priority</th>
                    <th>Owner</th>
                    <th>ID</th>
                </tr>
            </thead>
            <tbody id="records-table-body">
                {rows_html}
            </tbody>
        </table>
    </div>
    """
    return HTMLResponse(content=_layout("Records", content, user))


# ── Deterministic Inspection & Verification API ───────────────────────


@acceptance_app.get("/api/state")
async def get_state_summary():
    """Returns deterministic application state for automated acceptance verification."""
    return JSONResponse(
        status_code=200,
        content={
            "user_count": len(USERS),
            "users": list(USERS.keys()),
            "active_session_count": len(SESSIONS),
            "record_count": len(RECORDS),
            "records": RECORDS,
        },
    )


@acceptance_app.post("/api/reset")
async def post_reset_state():
    """Resets in-memory state to initial defaults."""
    reset_state()
    return JSONResponse(status_code=200, content={"status": "reset", "record_count": len(RECORDS)})
