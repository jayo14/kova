from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Enrollment Before Access Fixture")

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head><title>Course: Autonomous Systems</title></head>
<body>
  <h1>Autonomous Systems</h1>
  <div id="unregisteredSection">
    <p id="enrollmentStatus" style="color:orange;">Status: Enrollment Required</p>
    <p>You must enroll before accessing lesson modules and lecture materials.</p>
    <button id="enrollBtn">Enroll in Course</button>
  </div>

  <div id="enrolledSection" style="display:none;">
    <p id="enrolledStatus" style="color:green;">Status: Enrolled</p>
    <h3 id="lessonTitle">Course Access Granted</h3>
    <ul id="lessonList">
      <li>Module 1: Agent Architectures</li>
      <li>Module 2: Tool Calling & Verification</li>
    </ul>
  </div>

  <script>
    document.getElementById('enrollBtn').addEventListener('click', async function() {
      const res = await fetch('/api/course/enroll', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ course_id: 'auto-sys-101' })
      });
      if (res.ok) {
        document.getElementById('unregisteredSection').style.display = 'none';
        document.getElementById('enrolledSection').style.display = 'block';
      }
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/course/intro-to-ai", response_class=HTMLResponse)
async def get_course():
    return HTMLResponse(content=HTML_CONTENT)

@app.post("/api/course/enroll")
async def post_enroll(payload: dict | None = None):
    return JSONResponse(status_code=200, content={"status": "enrolled", "course_id": "auto-sys-101"})
