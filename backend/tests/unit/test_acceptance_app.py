"""Unit and integration tests for Kova Phase 1.5 controlled test application.

Verifies:
- Public landing page with working navigation
- Registration form validation (missing consent checkbox, short password, duplicate account)
- Successful registration with session creation
- Login validation and session authentication
- Protected route redirection when unauthenticated
- Dashboard rendering for authenticated users
- Record creation validation (minimum title length)
- Record creation success and persistence across requests
- Record list search and filtering functionality
- Deterministic API state inspection and reset
"""

import pytest
from httpx import ASGITransport, AsyncClient

from tests.fixtures.acceptance_app import acceptance_app, reset_state


@pytest.fixture(autouse=True)
def setup_state():
    reset_state()
    yield
    reset_state()


@pytest.mark.asyncio
async def test_public_landing_page_navigation():
    async with AsyncClient(transport=ASGITransport(app=acceptance_app), base_url="http://test") as client:
        res = await client.get("/")
        assert res.status_code == 200
        assert "Welcome to the Kova Acceptance Application" in res.text
        assert 'href="/register"' in res.text
        assert 'href="/login"' in res.text
        assert 'href="/about"' in res.text

        about_res = await client.get("/about")
        assert about_res.status_code == 200
        assert "About This Application" in about_res.text


@pytest.mark.asyncio
async def test_registration_validation_errors():
    async with AsyncClient(transport=ASGITransport(app=acceptance_app), base_url="http://test") as client:
        # 1. Missing consent checkbox
        res_no_consent = await client.post(
            "/register",
            data={
                "name": "Jane Doe",
                "email": "jane@kova.local",
                "password": "Password123!",
                "role": "user",
            },
        )
        assert res_no_consent.status_code == 422
        assert "agree to the Terms of Service" in res_no_consent.text

        # 2. Short password
        res_short_pw = await client.post(
            "/register",
            data={
                "name": "Jane Doe",
                "email": "jane@kova.local",
                "password": "123",
                "role": "user",
                "terms_consent": "agreed",
            },
        )
        assert res_short_pw.status_code == 422
        assert "at least 6 characters" in res_short_pw.text

        # 3. Duplicate account
        res_dup = await client.post(
            "/register",
            data={
                "name": "Existing User",
                "email": "testuser@kova.local",
                "password": "Password123!",
                "role": "user",
                "terms_consent": "agreed",
            },
        )
        assert res_dup.status_code == 409
        assert "already exists" in res_dup.text


@pytest.mark.asyncio
async def test_registration_and_login_success():
    async with AsyncClient(transport=ASGITransport(app=acceptance_app), base_url="http://test") as client:
        # Register new disposable user
        reg_res = await client.post(
            "/register",
            data={
                "name": "Sam Taylor",
                "email": "sam.taylor@kova.local",
                "password": "SecurePassword123!",
                "role": "manager",
                "terms_consent": "agreed",
            },
            follow_redirects=False,
        )
        assert reg_res.status_code == 303
        assert "/dashboard" in reg_res.headers["location"]
        session_cookie = reg_res.cookies.get("session_id")
        assert session_cookie is not None

        # Access dashboard with session cookie
        client.cookies.set("session_id", session_cookie)
        dash_res = await client.get("/dashboard")
        assert dash_res.status_code == 200
        assert "sam.taylor@kova.local" in dash_res.text
        assert "manager" in dash_res.text

        # Test explicit login with existing user
        client.cookies.clear()
        login_res = await client.post(
            "/login",
            data={"email": "testuser@kova.local", "password": "Password123!"},
            follow_redirects=False,
        )
        assert login_res.status_code == 303
        assert "/dashboard" in login_res.headers["location"]


@pytest.mark.asyncio
async def test_protected_routes_require_authentication():
    async with AsyncClient(transport=ASGITransport(app=acceptance_app), base_url="http://test") as client:
        # Without cookie -> redirect to login
        dash = await client.get("/dashboard", follow_redirects=False)
        assert dash.status_code == 302
        assert "/login" in dash.headers["location"]

        records = await client.get("/records", follow_redirects=False)
        assert records.status_code == 302
        assert "/login" in records.headers["location"]

        new_rec = await client.get("/records/new", follow_redirects=False)
        assert new_rec.status_code == 302
        assert "/login" in new_rec.headers["location"]


@pytest.mark.asyncio
async def test_record_creation_validation_and_persistence():
    async with AsyncClient(transport=ASGITransport(app=acceptance_app), base_url="http://test") as client:
        # Authenticate as testuser
        login = await client.post(
            "/login",
            data={"email": "testuser@kova.local", "password": "Password123!"},
            follow_redirects=False,
        )
        sess = login.cookies["session_id"]
        client.cookies.set("session_id", sess)

        # 1. Validation failure: short title
        res_fail = await client.post(
            "/records/new",
            data={"title": "ab", "category": "bug", "priority": "high", "description": "Too short"},
        )
        assert res_fail.status_code == 422
        assert "Title must be at least 3 characters" in res_fail.text

        # 2. Successful creation
        res_create = await client.post(
            "/records/new",
            data={
                "title": "Automated End-to-End Acceptance Record",
                "category": "feature",
                "priority": "high",
                "description": "Deterministic record created during automated verification test",
            },
            follow_redirects=False,
        )
        assert res_create.status_code == 303
        assert "/records?created=rec-" in res_create.headers["location"]

        # 3. Verify record listing and persistence
        res_list = await client.get("/records")
        assert res_list.status_code == 200
        assert "Automated End-to-End Acceptance Record" in res_list.text
        assert "Deterministic record created during automated verification test" in res_list.text

        # 4. Persistence check: refresh/second request
        res_refresh = await client.get("/records")
        assert res_refresh.status_code == 200
        assert "Automated End-to-End Acceptance Record" in res_refresh.text

        # 5. Programmatic state API inspection
        state_res = await client.get("/api/state")
        assert state_res.status_code == 200
        data = state_res.json()
        assert data["record_count"] >= 4
        assert any(r["title"] == "Automated End-to-End Acceptance Record" for r in data["records"])


@pytest.mark.asyncio
async def test_record_search_and_filtering():
    async with AsyncClient(transport=ASGITransport(app=acceptance_app), base_url="http://test") as client:
        login = await client.post(
            "/login",
            data={"email": "testuser@kova.local", "password": "Password123!"},
            follow_redirects=False,
        )
        sess = login.cookies["session_id"]
        client.cookies.set("session_id", sess)

        # Search by keyword matching rec-102
        res_search = await client.get("/records?q=Stripe")
        assert res_search.status_code == 200
        assert "Payment Gateway Integration" in res_search.text
        assert "Flaky Locator Diagnostic" not in res_search.text

        # Filter by category "bug"
        res_filter = await client.get("/records?category=bug")
        assert res_filter.status_code == 200
        assert "Flaky Locator Diagnostic" in res_filter.text
        assert "Payment Gateway Integration" not in res_filter.text

        # Search with non-matching term
        res_empty = await client.get("/records?q=NonExistentQueryZXY")
        assert res_empty.status_code == 200
        assert "No matching records found" in res_empty.text
