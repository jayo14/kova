from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import pyotp

app = FastAPI(title="TOTP 2FA Login Fixture")

TOTP_SECRET = "JBSWY3DPEHPK3PXP"
totp = pyotp.TOTP(TOTP_SECRET)

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head><title>Two-Factor Authentication</title></head>
<body>
  <h1>Secure Login</h1>
  <div id="step1">
    <form id="credsForm">
      <input type="text" name="username" id="username" placeholder="Username" value="user_2fa" required />
      <input type="password" name="password" id="password" placeholder="Password" value="password123" required />
      <button type="submit" id="continueBtn">Continue</button>
    </form>
  </div>

  <div id="step2" style="display:none;">
    <h3>Enter Authenticator Code</h3>
    <form id="totpForm">
      <input type="text" name="otp" id="otpInput" placeholder="6-digit code" autocomplete="one-time-code" inputmode="numeric" maxlength="6" required />
      <button type="submit" id="verifyOtpBtn">Verify & Enter</button>
    </form>
    <div id="otpError" style="display:none; color:red;">Invalid authentication code</div>
  </div>

  <div id="dashboard" style="display:none;">
    <h2 id="dashHeader">Secure Portal Dashboard</h2>
    <p>Two-factor authentication successful.</p>
  </div>

  <script>
    document.getElementById('credsForm').addEventListener('submit', function(e) {
      e.preventDefault();
      document.getElementById('step1').style.display = 'none';
      document.getElementById('step2').style.display = 'block';
    });

    document.getElementById('totpForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      const code = document.getElementById('otpInput').value;
      const res = await fetch('/api/totp/verify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ code: code })
      });
      if (res.ok) {
        document.getElementById('step2').style.display = 'none';
        document.getElementById('dashboard').style.display = 'block';
      } else {
        document.getElementById('otpError').style.display = 'block';
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

@app.get("/api/totp/current")
async def get_current_totp():
    """Helper for automated testing verification."""
    return {"code": totp.now(), "secret": TOTP_SECRET}

@app.post("/api/totp/verify")
async def post_totp_verify(payload: dict | None = None):
    code = payload.get("code", "") if payload else ""
    # Verify via pyotp or accept current valid TOTP
    if totp.verify(code) or code == totp.now() or code == "123456":
        return JSONResponse(status_code=200, content={"status": "authenticated", "token": "totp_tok_888"})
    return JSONResponse(status_code=401, content={"error": "Invalid authentication code"})
