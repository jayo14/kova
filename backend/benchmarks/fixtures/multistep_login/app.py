from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Multi-Step Login Fixture")

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head><title>Multi-Step Sign In</title></head>
<body>
  <h1>Sign In</h1>
  <div id="step1">
    <h3>Step 1: Enter your identifier</h3>
    <form id="step1Form">
      <input type="text" name="identifier" id="identifier" placeholder="Email or Username" required />
      <button type="submit" id="nextBtn">Next</button>
    </form>
  </div>

  <div id="step2" style="display:none;">
    <h3>Step 2: Enter password</h3>
    <form id="step2Form">
      <p id="selectedUser" style="color: #666;"></p>
      <input type="password" name="password" id="password" placeholder="Password" required />
      <button type="submit" id="signInBtn">Sign In</button>
    </form>
  </div>

  <div id="dashboard" style="display:none;">
    <h2 id="dashWelcome">Multi-Step Dashboard</h2>
    <p>Authentication complete across multiple steps.</p>
  </div>

  <script>
    let savedIdentifier = '';
    document.getElementById('step1Form').addEventListener('submit', function(e) {
      e.preventDefault();
      savedIdentifier = document.getElementById('identifier').value;
      document.getElementById('selectedUser').innerText = 'Signing in as: ' + savedIdentifier;
      document.getElementById('step1').style.display = 'none';
      document.getElementById('step2').style.display = 'block';
    });

    document.getElementById('step2Form').addEventListener('submit', async function(e) {
      e.preventDefault();
      const res = await fetch('/api/login/finish', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          identifier: savedIdentifier,
          password: document.getElementById('password').value
        })
      });
      if (res.ok) {
        document.getElementById('step2').style.display = 'none';
        document.getElementById('dashboard').style.display = 'block';
      }
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
async def get_login():
    return HTMLResponse(content=HTML_CONTENT)

@app.post("/api/login/finish")
async def post_login_finish(payload: dict | None = None):
    if payload and payload.get("password") in ("wrong", "invalid"):
        return JSONResponse(status_code=401, content={"error": "Invalid password"})
    return JSONResponse(status_code=200, content={"status": "authenticated", "token": "mstep_tok_99"})
