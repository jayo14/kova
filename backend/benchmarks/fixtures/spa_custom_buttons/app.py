from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="SPA with Custom Div Buttons Fixture")

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head>
  <title>Editor - Custom Components</title>
  <style>
    .custom-btn {
      display: inline-block;
      padding: 10px 20px;
      margin: 8px 4px;
      cursor: pointer;
      user-select: none;
      border-radius: 6px;
      background: #e2e8f0;
      color: #1e293b;
      font-weight: 500;
    }
    .custom-btn.primary { background: #3b82f6; color: #ffffff; }
    .custom-btn:hover { opacity: 0.9; }
  </style>
</head>
<body>
  <h1>Interactive Article Editor</h1>
  <div id="editorContent">
    <input type="text" id="articleTitle" value="Building Resilient AI Agents" style="font-size: 1.2rem; width: 80%; padding: 8px;" />
  </div>

  <div id="customButtonToolbar" style="margin-top: 20px;">
    <!-- Non-standard interactive div buttons -->
    <div class="custom-btn" role="button" tabindex="0" id="saveDraftDiv">Save Draft</div>
    <div class="custom-btn primary" role="button" tabindex="0" id="publishArticleDiv">Publish Article</div>
  </div>

  <div id="feedbackArea" style="margin-top: 20px;"></div>

  <script>
    document.getElementById('publishArticleDiv').addEventListener('click', async function() {
      const res = await fetch('/api/articles/publish', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ title: document.getElementById('articleTitle').value })
      });
      if (res.ok) {
        document.getElementById('feedbackArea').innerHTML = '<div id="statusBadge" class="published" style="color:green; font-weight:bold;">Article Published Successfully</div>';
      }
    });

    document.getElementById('saveDraftDiv').addEventListener('click', function() {
      document.getElementById('feedbackArea').innerHTML = '<div id="draftBadge">Draft Saved</div>';
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/editor", response_class=HTMLResponse)
async def get_editor():
    return HTMLResponse(content=HTML_CONTENT)

@app.post("/api/articles/publish")
async def post_publish(payload: dict | None = None):
    return JSONResponse(status_code=200, content={"status": "published", "id": "art_101"})
