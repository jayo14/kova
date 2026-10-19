from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Working Auth Flow")

LOGIN_HTML = """<!DOCTYPE html>
<html>
<head><title>Login</title></head>
<body>
  <h1>User Login</h1>
  <form id="loginForm">
    <input type="text" name="username" id="username" placeholder="Username" required />
    <input type="password" name="password" id="password" placeholder="Password" required />
    <button type="submit" id="loginBtn">Log In</button>
  </form>
  <div id="result"></div>
  <script>
    document.getElementById('loginForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username: this.username.value,
          password: this.password.value
        })
      });
      if (res.ok) {
        window.location.href = '/dashboard';
      }
    });
  </script>
</body>
</html>
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head><title>Dashboard</title></head>
<body>
  <h1>Welcome to your Dashboard</h1>
  <p id="welcome">Logged in successfully</p>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
async def get_login():
    return HTMLResponse(content=LOGIN_HTML)

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)

@app.post("/api/login")
async def post_login():
    return JSONResponse(status_code=200, content={"status": "authenticated", "token": "tok_123"})
