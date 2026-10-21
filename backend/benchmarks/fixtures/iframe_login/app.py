from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Login Inside Iframe Fixture")

PARENT_HTML = """<!DOCTYPE html>
<html>
<head><title>Partner SSO Portal</title></head>
<body>
  <h1>Partner SSO Portal</h1>
  <div id="parentStatus">Awaiting authentication inside secure frame...</div>
  <div id="frameWrapper" style="margin-top: 15px;">
    <iframe id="authFrame" src="/frame/login" style="width: 450px; height: 280px; border: 1px solid #cbd5e1; border-radius: 6px;"></iframe>
  </div>

  <script>
    window.addEventListener('message', function(event) {
      if (event.data && event.data.type === 'AUTH_SUCCESS') {
        document.getElementById('parentStatus').innerHTML = '<h2 id="iframeSuccess">Authenticated in Iframe Workspace</h2><p>Welcome, partner administrator.</p>';
        document.getElementById('frameWrapper').style.display = 'none';
      }
    });
  </script>
</body>
</html>
"""

FRAME_HTML = """<!DOCTYPE html>
<html>
<head><title>Embedded Sign In</title></head>
<body style="font-family: sans-serif; padding: 10px;">
  <h3>Embedded Sign In</h3>
  <form id="frameLoginForm">
    <p><input type="text" name="username" id="frameUsername" placeholder="Username" value="partner_admin" required /></p>
    <p><input type="password" name="password" id="framePassword" placeholder="Password" value="secure_pass_123" required /></p>
    <p><button type="submit" id="frameLoginBtn">Authorize Partner</button></p>
  </form>
  <div id="frameError" style="display:none; color:red;">Invalid credentials</div>

  <script>
    document.getElementById('frameLoginForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      const res = await fetch('/api/frame/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username: this.username.value,
          password: this.password.value
        })
      });
      if (res.ok) {
        window.parent.postMessage({ type: 'AUTH_SUCCESS' }, '*');
      } else {
        document.getElementById('frameError').style.display = 'block';
      }
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/portal", response_class=HTMLResponse)
async def get_portal():
    return HTMLResponse(content=PARENT_HTML)

@app.get("/frame/login", response_class=HTMLResponse)
async def get_frame_login():
    return HTMLResponse(content=FRAME_HTML)

@app.post("/api/frame/login")
async def post_frame_login(payload: dict | None = None):
    if payload and payload.get("password") in ("wrong", "invalid"):
        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
    return JSONResponse(status_code=200, content={"status": "authenticated", "token": "iframe_sso_tok"})
