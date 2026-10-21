from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

app = FastAPI(title="Redirect After Login Fixture")

LOGIN_HTML = """<!DOCTYPE html>
<html>
<head><title>Login Required</title></head>
<body>
  <h1>Sign In</h1>
  <p id="redirectNotice">Please sign in to view requested resource.</p>
  <form id="loginForm">
    <input type="text" name="username" id="username" placeholder="Username" required />
    <input type="password" name="password" id="password" placeholder="Password" required />
    <button type="submit" id="loginBtn">Log In</button>
  </form>
  <script>
    document.getElementById('loginForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      const params = new URLSearchParams(window.location.search);
      const nextUrl = params.get('next') || '/dashboard';
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username: this.username.value,
          password: this.password.value,
          next: nextUrl
        })
      });
      if (res.ok) {
        const data = await res.json();
        window.location.href = data.redirect_to;
      }
    });
  </script>
</body>
</html>
"""

REPORTS_HTML = """<!DOCTYPE html>
<html>
<head><title>Financial Reports</title></head>
<body>
  <h1>Financial Reports</h1>
  <p id="reportContent">Financial Reports - Access Granted</p>
  <p>Q3 Revenue Breakdown</p>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_root():
    return HTMLResponse(content="<h1>Welcome</h1><a href='/reports/financial' id='reportsLink'>View Financial Reports</a>")

@app.get("/reports/financial", response_class=HTMLResponse)
async def get_financial_reports(request: Request):
    # Simulates requiring auth: if no cookie/auth header, redirect to /login
    auth_header = request.headers.get("Authorization")
    auth_cookie = request.cookies.get("session_token")
    if not auth_header and not auth_cookie:
        return RedirectResponse(url="/login?next=%2Freports%2Ffinancial", status_code=302)
    return HTMLResponse(content=REPORTS_HTML)

@app.get("/login", response_class=HTMLResponse)
async def get_login():
    return HTMLResponse(content=LOGIN_HTML)

@app.post("/api/login")
async def post_login(payload: dict | None = None):
    redirect_to = payload.get("next", "/dashboard") if payload else "/dashboard"
    resp = JSONResponse(status_code=200, content={"status": "ok", "redirect_to": redirect_to})
    resp.set_cookie(key="session_token", value="sess_redirect_test", path="/")
    return resp
