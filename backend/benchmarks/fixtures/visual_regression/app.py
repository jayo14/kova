from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Visual Regression Demo")

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head><title>Visual Regression Demo</title></head>
<body>
  <h1>Product Showcase</h1>
  <div class="container" style="position: relative; width: 600px; height: 400px; overflow: hidden; border: 1px solid #ccc;">
    <h2>Special Offer</h2>
    <p>Sign up now to receive exclusive updates.</p>
    <!-- Visual bug: primary button shifted 50px off-canvas -->
    <button id="ctaBtn" style="position: absolute; left: -50px; top: 150px; padding: 12px 24px; background: #3b82f6; color: white; border: none; border-radius: 4px;">Claim Offer</button>
  </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_root():
    return HTMLResponse(content=HTML_CONTENT)
