from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Modal Login Fixture")

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head>
  <title>Portal with Modal Login</title>
  <style>
    .modal { display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); }
    .modal-content { background: #fff; margin: 15% auto; padding: 20px; border-radius: 8px; width: 300px; }
  </style>
</head>
<body>
  <h1>Welcome to Acme Cloud</h1>
  <div id="authNav">
    <button id="openModalBtn" onclick="document.getElementById('loginModal').style.display='block'">Sign In</button>
  </div>
  <div id="dashboardArea" style="display:none;">
    <h2 id="userGreeting">Welcome back, testuser!</h2>
    <p>Your cloud dashboard is ready.</p>
  </div>

  <div id="loginModal" class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <div class="modal-content">
      <h3 id="modalTitle">Sign In to Acme</h3>
      <form id="modalLoginForm">
        <p><input type="text" name="username" id="modalUsername" placeholder="Username" required /></p>
        <p><input type="password" name="password" id="modalPassword" placeholder="Password" required /></p>
        <p><button type="submit" id="modalSubmitBtn">Log In</button></p>
      </form>
      <div id="modalError" style="display:none; color: red;">Invalid credentials</div>
    </div>
  </div>

  <script>
    document.getElementById('modalLoginForm').addEventListener('submit', async function(e) {
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
        document.getElementById('loginModal').style.display = 'none';
        document.getElementById('authNav').style.display = 'none';
        document.getElementById('dashboardArea').style.display = 'block';
      } else {
        document.getElementById('modalError').style.display = 'block';
      }
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/portal", response_class=HTMLResponse)
async def get_portal():
    return HTMLResponse(content=HTML_CONTENT)

@app.post("/api/login")
async def post_login(payload: dict | None = None):
    # Valid credentials
    if payload and payload.get("username") == "testuser" and payload.get("password") == "correct_password":
        return JSONResponse(status_code=200, content={"status": "authenticated", "token": "modal_tok_123"})
    # Also accept standard test credentials
    if payload and payload.get("password") not in ("wrong", "invalid"):
        return JSONResponse(status_code=200, content={"status": "authenticated", "token": "modal_tok_123"})
    return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
