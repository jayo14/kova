from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Session Expiry Fixture")

PROFILE_HTML = """<!DOCTYPE html>
<html>
<head><title>User Profile</title></head>
<body>
  <h1>User Profile</h1>
  <p>Status: Active</p>
  <form id="profileForm">
    <input type="text" name="display_name" id="displayName" value="Alice Smith" required />
    <button type="submit" id="saveProfileBtn">Save Profile</button>
  </form>
  <div id="notice"></div>
  <script>
    document.getElementById('profileForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      const res = await fetch('/api/profile/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ display_name: document.getElementById('displayName').value })
      });
      if (res.status === 401) {
        document.getElementById('notice').innerHTML = '<div id="expiryNotice" class="error" style="color:red;">Your session has expired. Please log in again.</div>';
      } else {
        document.getElementById('notice').innerHTML = '<div class="success">Profile saved.</div>';
      }
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/profile", response_class=HTMLResponse)
async def get_profile():
    return HTMLResponse(content=PROFILE_HTML)

@app.post("/api/profile/update")
async def post_profile_update():
    # Seeded defect: session prematurely expires causing 401
    return JSONResponse(status_code=401, content={"error": "Session expired", "code": "SESSION_EXPIRED"})
