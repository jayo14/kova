from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import random

app = FastAPI(title="Email OTP Login Fixture")

# In-memory mock mailbox for internal temp mail
INBOX: dict[str, list[dict]] = {}

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head><title>Sign In with Email Code</title></head>
<body>
  <h1>Email OTP Login</h1>
  <div id="requestOtp">
    <form id="emailForm">
      <input type="email" name="email" id="emailInput" placeholder="Enter work email" value="tester@kova.internal" required />
      <button type="submit" id="sendOtpBtn">Send Login Code</button>
    </form>
  </div>

  <div id="verifyOtp" style="display:none;">
    <p>A verification code was sent to your email.</p>
    <form id="codeForm">
      <input type="text" name="code" id="otpField" placeholder="6-digit code" autocomplete="one-time-code" maxlength="6" required />
      <button type="submit" id="verifyEmailOtpBtn">Verify & Sign In</button>
    </form>
    <div id="error" style="display:none; color:red;">Incorrect code</div>
  </div>

  <div id="dashboard" style="display:none;">
    <h2 id="successHeader">Email Verified Dashboard</h2>
    <p>Welcome to your verified workspace.</p>
  </div>

  <script>
    let currentEmail = '';
    document.getElementById('emailForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      currentEmail = document.getElementById('emailInput').value;
      const res = await fetch('/api/otp/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ email: currentEmail })
      });
      if (res.ok) {
        document.getElementById('requestOtp').style.display = 'none';
        document.getElementById('verifyOtp').style.display = 'block';
      }
    });

    document.getElementById('codeForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      const code = document.getElementById('otpField').value;
      const res = await fetch('/api/otp/verify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ email: currentEmail, code: code })
      });
      if (res.ok) {
        document.getElementById('verifyOtp').style.display = 'none';
        document.getElementById('dashboard').style.display = 'block';
      } else {
        document.getElementById('error').style.display = 'block';
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

@app.post("/api/otp/send")
async def post_send_otp(payload: dict | None = None):
    email = payload.get("email", "tester@kova.internal") if payload else "tester@kova.internal"
    code = f"{random.randint(100000, 999999)}"
    if email not in INBOX:
        INBOX[email] = []
    INBOX[email].append({"code": code, "subject": "Your Login Code"})
    return {"status": "sent", "code": code}

@app.get("/api/inbox/{email}")
async def get_inbox(email: str):
    """Internal temp mail inbox query."""
    messages = INBOX.get(email, [])
    return {"email": email, "messages": messages, "latest_code": messages[-1]["code"] if messages else "123456"}

@app.post("/api/otp/verify")
async def post_verify_otp(payload: dict | None = None):
    email = payload.get("email", "") if payload else ""
    code = payload.get("code", "") if payload else ""
    messages = INBOX.get(email, [])
    valid_codes = [m["code"] for m in messages] + ["123456"]
    if code in valid_codes:
        return JSONResponse(status_code=200, content={"status": "authenticated", "token": "email_tok_777"})
    return JSONResponse(status_code=401, content={"error": "Invalid verification code"})
