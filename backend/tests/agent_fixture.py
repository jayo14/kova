"""Agent test application: a realistic authentication lifecycle app.

Supports: signup → email verification → login → logout → forgot password →
password reset — with THREE UI variants that differ in layout and label text
but share the same semantic flow. Proves the agent learned the task, not one
DOM (spec §30).

Runs together with the Kova fixture mail service (mail_service app below):
  POST /mailboxes                -> {"id","address"}
  GET  /mailboxes/{id}/messages  -> [{"sender","subject","body","received_at"}]
  DELETE /mailboxes/{id}

Accounts live in-process: signup records the account with a pending-verification
token delivered BY EMAIL (the app never reveals it in the DOM), verification
activates it, forgot-password emails a reset token, reset consumes the token.

Variant selection: query param ?v=a|b|c on every page (default a).
"""

import secrets
import time
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse

agent_app = FastAPI(title="Kova Agent Fixture")
mail_service = FastAPI(title="Kova Fixture Mail Service")

# ── In-process state ────────────────────────────────────────────────

ACCOUNTS: dict[str, dict] = {}          # email -> {password, verified}
PENDING_VERIFICATION: dict[str, str] = {}  # email -> token
RESET_TOKENS: dict[str, tuple[str, float]] = {}  # token -> (email, created_at)
SESSIONS: dict[str, str] = {}           # session_id -> email

# mailboxes: id -> {"address", "messages": [...]}
MAILBOXES: dict[str, dict] = {}
MAIL_DOMAIN = "mail.testfixture.local"

APP_PORT = 8300
MAIL_PORT = 8200


def _variant(request: Request) -> str:
    return (request.query_params.get("v") or "a").lower()


# ── Mail service ────────────────────────────────────────────────────


@mail_service.post("/mailboxes")
async def create_mailbox(body: dict | None = None):
    mailbox_id = secrets.token_hex(8)
    hint = (body or {}).get("hint") or "user"
    address = f"{hint}-{mailbox_id[:6]}@{MAIL_DOMAIN}"
    MAILBOXES[mailbox_id] = {"address": address, "messages": []}
    return {"id": mailbox_id, "address": address}


@mail_service.get("/mailboxes/{mailbox_id}/messages")
async def list_messages(mailbox_id: str):
    box = MAILBOXES.get(mailbox_id)
    if not box:
        return {"messages": []}
    return {"messages": box["messages"]}


@mail_service.delete("/mailboxes/{mailbox_id}")
async def delete_mailbox(mailbox_id: str):
    MAILBOXES.pop(mailbox_id, None)
    return {"ok": True}


def deliver_email(to_email: str, sender: str, subject: str, body: str) -> None:
    """Called by the app to deliver mail into the matching fixture mailbox."""
    for box in MAILBOXES.values():
        if box["address"].lower() == to_email.lower():
            box["messages"].append({
                "sender": sender,
                "subject": subject,
                "body": body,
                "received_at": time.time(),
            })
            return


# ── Page templates (3 semantic variants) ────────────────────────────


def _page(title: str, body: str, v: str, authenticated: bool = False) -> str:
    # The user menu (with Log Out) only appears when a session exists —
    # otherwise every page leaks an authenticated signal to observers.
    user_menu = (
        f"<span id='user-menu'>Account</span><a href='/logout?v={v}' id='logout-link'>Log Out</a>"
        if authenticated else ""
    )
    modal = ""
    if v == "m":
        modal = """
        <dialog open id="cookie-banner" role="dialog" style="position:fixed; bottom:10px; background:#fff; border:1px solid #ccc; padding:15px; z-index:9999;">
            <p>We use cookies to improve your experience.</p>
            <button type="button" id="accept-cookies" onclick="this.parentElement.close(); this.parentElement.style.display='none';">Accept all</button>
        </dialog>
        """
    return f"""<!DOCTYPE html>
<html><head><title>{title}</title></head>
<body>
{modal}
<nav>
    <a href="/?v={v}">Home</a>
    {user_menu}
</nav>
{body}
</body></html>"""


VARIANTS = {
    "a": {
        "signup_link": "Sign up",
        "login_link": "Log in",
        "email_label": "Email",
        "password_label": "Password",
        "submit": "Sign in",
        "recovery": "Forgot password?",
        "recovery_submit": "Send reset link",
        "reset_title": "Choose a new password",
        "reset_submit": "Save password",
    },
    "b": {
        "signup_link": "Create Account",
        "login_link": "Member Login",
        "email_label": "E-mail Address",
        "password_label": "Passphrase",
        "submit": "Enter",
        "recovery": "Reset your password",
        "recovery_submit": "Email me a recovery link",
        "reset_title": "Set your new passphrase",
        "reset_submit": "Update Passphrase",
    },
    "c": {
        "signup_link": "Register here",
        "login_link": "Access your account",
        "email_label": "Your email",
        "password_label": "Secret key",
        "submit": "Access",
        "recovery": "Can't access your account?",
        "recovery_submit": "Recover",
        "reset_title": "New secret key",
        "reset_submit": "Confirm new key",
    },
    "d": {
        "signup_link": "Join the service",
        "login_link": "Sign In to Portal",
        "email_label": "Work Email",
        "password_label": "Access Key",
        "submit": "Sign In",
        "recovery": "Need help signing in?",
        "recovery_submit": "Send Help Link",
        "reset_title": "Set New Access Key",
        "reset_submit": "Update Access Key",
    },
    "e": {
        "signup_link": "Sign up",
        "login_link": "Log in",
        "email_label": "Email",
        "password_label": "Password",
        "submit": "Sign in",
        "recovery": "Forgot password?",
        "recovery_submit": "Send reset link",
        "reset_title": "Choose a new password",
        "reset_submit": "Save password",
    },
    "g": {
        "signup_link": "Sign up",
        "login_link": "Log in",
        "email_label": "Email",
        "password_label": "Password",
        "submit": "Sign in",
        "recovery": "Trouble accessing your account?",
        "recovery_submit": "Recover account",
        "reset_title": "Choose a new password",
        "reset_submit": "Save password",
    },
    "i": {
        "signup_link": "Sign up",
        "login_link": "Log in",
        "email_label": "Email",
        "password_label": "Password",
        "submit": "Sign in",
        "recovery": "Reset password",
        "recovery_submit": "Send recovery instructions",
        "reset_title": "Set a new password",
        "reset_submit": "Save password",
    },
    "j": {
        "signup_link": "Create profile",
        "login_link": "Sign in to continue",
        "email_label": "Email address",
        "password_label": "Password",
        "submit": "Continue",
        "recovery": "Trouble signing in",
        "recovery_submit": "Send recovery link",
        "reset_title": "Update password",
        "reset_submit": "Set password",
    },
    "m": {
        "signup_link": "Sign up",
        "login_link": "Log in",
        "email_label": "Email",
        "password_label": "Password",
        "submit": "Sign in",
        "recovery": "Forgot password?",
        "recovery_submit": "Send reset link",
        "reset_title": "Choose a new password",
        "reset_submit": "Save password",
    },
}


def _login_page(v: str, error: str = "") -> str:
    L = VARIANTS.get(v, VARIANTS["a"])
    err = f"<div class='error' role='alert'>{error}</div>" if error else ""
    modal_recovery = ""
    if v == "g":
        modal_recovery = f"""
        <dialog open id="recovery-modal" role="dialog" style="margin-top:20px; border:1px solid #aaa; padding:15px;">
            <h2>{L['recovery']}</h2>
            <form method="post" action="/forgot?v={v}">
                <label for="recovery-email">{L['email_label']}</label>
                <input type="email" id="recovery-email" name="email" required />
                <button type="submit" id="modal-recover-btn">{L['recovery_submit']}</button>
            </form>
        </dialog>
        """
    return _page("Sign in", f"""
    <main>
        <h1>{L['login_link']}</h1>
        {err}
        <form method="post" action="/login?v={v}">
            <label for="email">{L['email_label']}</label>
            <input type="email" id="email" name="email" required />
            <label for="password">{L['password_label']}</label>
            <input type="password" id="password" name="password" required />
            <button type="submit" id="login-btn">{L['submit']}</button>
        </form>
        <a href="/signup?v={v}" id="signup-link">{L['signup_link']}</a>
        <a href="/forgot?v={v}" id="forgot-link">{L['recovery']}</a>
        {modal_recovery}
    </main>""", v)


def _signup_page(v: str) -> str:
    L = VARIANTS[v]
    return _page("Register", f"""
    <main>
        <h1>{L['signup_link']}</h1>
        <form method="post" action="/signup?v={v}">
            <label for="email">{L['email_label']}</label>
            <input type="email" id="email" name="email" required />
            <label for="password">{L['password_label']}</label>
            <input type="password" id="password" name="password" required />
            <button type="submit" id="signup-btn">Create</button>
        </form>
    </main>""", v)


def _forgot_page(v: str) -> str:
    L = VARIANTS[v]
    return _page("Recovery", f"""
    <main>
        <h1>{L['recovery']}</h1>
        <form method="post" action="/forgot?v={v}">
            <label for="email">{L['email_label']}</label>
            <input type="email" id="email" name="email" required />
            <button type="submit" id="recover-btn">{L['recovery_submit']}</button>
        </form>
    </main>""", v)


def _reset_page(v: str, token: str, error: str = "") -> str:
    L = VARIANTS[v]
    err = f"<div class='error' role='alert'>{error}</div>" if error else ""
    return _page(L["reset_title"], f"""
    <main>
        <h1>{L['reset_title']}</h1>
        {err}
        <form method="post" action="/reset?v={v}">
            <input type="hidden" name="token" value="{token}" />
            <label for="new-password">New {L['password_label']}</label>
            <input type="password" id="new-password" name="password" required />
            <label for="confirm-password">Confirm</label>
            <input type="password" id="confirm-password" name="confirm" required />
            <button type="submit" id="reset-btn">{L['reset_submit']}</button>
        </form>
    </main>""", v)


# ── Routes ──────────────────────────────────────────────────────────


@agent_app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    v = _variant(request)
    session = request.cookies.get("session")
    if session and session in SESSIONS:
        return _page("Home", "<main><h1>Welcome back to your dashboard</h1>"
                             "<a href='/logout?v=" + v + "' id='logout-link'>Log Out</a></main>", v, authenticated=True)
    return _login_page(v)


@agent_app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return _login_page(_variant(request))


@agent_app.post("/login")
async def login_post(request: Request, email: str = Form(""), password: str = Form("")):
    v = _variant(request)
    account = ACCOUNTS.get(email.lower())
    if not account or account["password"] != password:
        return HTMLResponse(_login_page(v, "Invalid credentials"), status_code=401)
    if not account["verified"]:
        return HTMLResponse(_login_page(v, "Please verify your email first"), status_code=403)
    session_id = secrets.token_hex(16)
    SESSIONS[session_id] = email.lower()
    response = RedirectResponse(url=f"/dashboard?v={v}", status_code=303)
    response.set_cookie("session", session_id, httponly=True, max_age=3600)
    return response


@agent_app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    v = _variant(request)
    session = request.cookies.get("session")
    if not session or session not in SESSIONS:
        return RedirectResponse(url=f"/login?v={v}", status_code=307)
    email = SESSIONS[session]
    return _page("Dashboard", f"<main><h1>Dashboard</h1><p id='user-email'>Signed in as {email}</p>"
                              f"<a href='/logout?v={v}' id='logout-link'>Log Out</a></main>", v, authenticated=True)


@agent_app.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    return _signup_page(_variant(request))


@agent_app.post("/signup")
async def signup_post(request: Request, email: str = Form(""), password: str = Form("")):
    v = _variant(request)
    email = email.lower()
    if email in ACCOUNTS:
        return HTMLResponse(_signup_page(v), status_code=409)
    ACCOUNTS[email] = {"password": password, "verified": False}
    token = secrets.token_hex(16)
    PENDING_VERIFICATION[email] = token
    # Build the link from the request's actual host so email-link validation
    # (same-host policy) accepts it no matter where the fixture is mounted.
    base = str(request.base_url).rstrip("/")
    link = f"{base}/verify?token={token}&v={v}"
    deliver_email(
        email,
        "no-reply@testfixture.local",
        "Verify your email address",
        f"Thanks for signing up! Please confirm your account: {link}\n"
        f"This link verifies your email address.",
    )
    return HTMLResponse(_page("Check email",
                              "<main><h1>Check your email to verify your account.</h1>"
                              "<p id='verify-prompt'>We sent a confirmation link to your inbox.</p></main>", v))


@agent_app.get("/verify")
async def verify(request: Request, token: str = ""):
    v = _variant(request)
    email = next((e for e, t in PENDING_VERIFICATION.items() if t == token), None)
    if not email:
        return HTMLResponse(_page("Invalid", "<main><h1>Invalid verification link</h1></main>", v), status_code=400)
    PENDING_VERIFICATION.pop(email)
    ACCOUNTS[email]["verified"] = True
    return RedirectResponse(url=f"/login?v={v}&verified=1", status_code=303)


@agent_app.get("/logout")
async def logout(request: Request):
    v = _variant(request)
    session = request.cookies.get("session")
    SESSIONS.pop(session, None)
    response = RedirectResponse(url=f"/login?v={v}", status_code=303)
    response.delete_cookie("session")
    return response


@agent_app.get("/forgot", response_class=HTMLResponse)
async def forgot_get(request: Request):
    return _forgot_page(_variant(request))


@agent_app.post("/forgot")
async def forgot_post(request: Request, email: str = Form("")):
    v = _variant(request)
    email = email.lower()
    if email in ACCOUNTS and ACCOUNTS[email]["verified"]:
        token = secrets.token_hex(16)
        RESET_TOKENS[token] = (email, time.time())
        base = str(request.base_url).rstrip("/")
        link = f"{base}/reset?token={token}&v={v}"
        if v == "i":
            # Variant I: multi-link distractors (unsubscribe, terms, privacy, help)
            body = (
                f"Security notice for your account.\n\n"
                f"Privacy policy: {base}/privacy\n"
                f"Terms of Service: {base}/terms\n"
                f"To reset your password, visit: {link}\n"
                f"Unsubscribe from emails: {base}/unsubscribe?user=123\n"
                f"Help Center: {base}/help\n"
            )
            deliver_email(
                email,
                "security@testfixture.local",
                "Reset your password",
                body,
            )
        elif v == "j":
            deliver_email(
                email,
                "auth-service@testfixture.local",
                "Instructions to reset your password",
                f"Someone requested recovery. Follow instructions: {link}",
            )
        else:
            deliver_email(
                email,
                "security@testfixture.local",
                "Reset your password",
                f"A password reset was requested for your account. "
                f"Open this link to choose a new password: {link}\n"
                f"The link expires soon.",
            )
    # Anti-enumeration: same response regardless of account existence
    return HTMLResponse(_page("Recovery requested",
                              "<main><h1>Check your inbox</h1>"
                              "<p id='reset-sent'>If that account exists, recovery instructions "
                              "have been sent to your email.</p></main>", v))


@agent_app.get("/reset", response_class=HTMLResponse)
async def reset_get(request: Request, token: str = ""):
    v = _variant(request)
    entry = RESET_TOKENS.get(token)
    if not entry or time.time() - entry[1] > 900:
        return HTMLResponse(_page("Expired", "<main><h1>This reset link is expired or invalid</h1></main>", v), status_code=400)
    return _reset_page(v, token)


@agent_app.post("/reset")
async def reset_post(request: Request, token: str = Form(""), password: str = Form(""), confirm: str = Form("")):
    v = _variant(request)
    entry = RESET_TOKENS.pop(token, None)
    if not entry or time.time() - entry[1] > 900:
        return HTMLResponse(_page("Expired", "<main><h1>This reset link is expired or invalid</h1></main>", v), status_code=400)
    if password != confirm:
        # Token is single-use but mismatch keeps a fresh token to retry fairly
        RESET_TOKENS[secrets.token_hex(16)] = (entry[0], time.time())
        return HTMLResponse(_reset_page(v, "", "Passwords do not match"), status_code=400)
    email = entry[0]
    ACCOUNTS[email]["password"] = password
    return HTMLResponse(_page("Password updated",
                              "<main><h1>Password updated</h1>"
                              "<p id='reset-success'>Your password has been changed. "
                              "You can now sign in with your new password.</p>"
                              f"<a href='/login?v={v}' id='login-link'>Log in</a></main>", v))


@agent_app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    return HTMLResponse("<html><body><h1>Privacy Policy</h1></body></html>")


@agent_app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    return HTMLResponse("<html><body><h1>Terms of Service</h1></body></html>")


@agent_app.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_page():
    return HTMLResponse("<html><body><h1>Unsubscribed</h1></body></html>")


@agent_app.get("/help", response_class=HTMLResponse)
async def help_page():
    return HTMLResponse("<html><body><h1>Help Center</h1></body></html>")


def seed_account(email: str, password: str = "OldPassword123!") -> None:
    """Pre-seed an account for existing-account test scenarios."""
    ACCOUNTS[email.lower()] = {"password": password, "verified": True}
