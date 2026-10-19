from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Working Contact Form")

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head><title>Contact Form</title></head>
<body>
  <h1>Contact Us</h1>
  <form id="contactForm">
    <input type="text" name="name" placeholder="Name" required />
    <input type="email" name="email" placeholder="Email" required />
    <textarea name="message" placeholder="Message" required></textarea>
    <button type="submit" id="submitBtn">Send Message</button>
  </form>
  <div id="result"></div>
  <script>
    document.getElementById('contactForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          name: this.name.value,
          email: this.email.value,
          message: this.message.value
        })
      });
      if (res.ok) {
        document.getElementById('result').innerHTML = '<div class="success">Thank you! Your message has been sent.</div>';
      } else {
        document.getElementById('result').innerHTML = '<div class="error">Failed to send message.</div>';
      }
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/contact", response_class=HTMLResponse)
async def get_contact():
    return HTMLResponse(content=HTML_CONTENT)

@app.post("/api/contact")
async def post_contact():
    return JSONResponse(status_code=200, content={"status": "ok"})
