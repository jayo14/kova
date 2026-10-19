from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Permission Escalation Demo")

PORTAL_HTML = """<!DOCTYPE html>
<html>
<head><title>Teacher Portal</title></head>
<body>
  <h1>Teacher Portal</h1>
  <p>Welcome, Teacher.</p>
  <a href="/admin" id="adminLink">Admin Settings</a>
</body>
</html>
"""

ADMIN_HTML = """<!DOCTYPE html>
<html>
<head><title>Admin Console</title></head>
<body>
  <h1>Admin Console</h1>
  <p>Sensitive administration settings accessible without admin privilege check.</p>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/portal", response_class=HTMLResponse)
async def get_portal():
    return HTMLResponse(content=PORTAL_HTML)

@app.get("/admin", response_class=HTMLResponse)
async def get_admin():
    # Defect: Allows access to non-admin roles without 403 Forbidden
    return HTMLResponse(content=ADMIN_HTML)
