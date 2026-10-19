from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Buggy Auth Flow")

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
  <div id="error" class="error" style="display:none; color: red;">Authentication failed.</div>
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
      // Bug: always fails authentication and stays on login page
      document.getElementById('error').style.display = 'block';
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
async def get_login():
    return HTMLResponse(content=LOGIN_HTML)

@app.post("/api/login")
async def post_login():
    return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
