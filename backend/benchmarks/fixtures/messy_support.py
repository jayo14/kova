"""Generic, local-only page patterns for the messy-site benchmark tier."""

import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse


PAGES = {
    "unlabeled_controls": """<main><h1>Control samples</h1>
<div onclick="document.querySelector('#state').textContent='div activated'">Continue</div>
<button onclick="document.querySelector('#state').textContent='icon activated'"><svg aria-hidden="true"><circle r="4"/></svg></button>
<button aria-label="Save item" onclick="document.querySelector('#state').textContent='saved'">✓</button>
<p id="state">idle</p></main>""",
    "unassociated_inputs": """<main><h1>Profile details</h1>
<label>Name</label><input placeholder="Your name">
<label for="different-id">Email</label><input id="email" placeholder="name@example.test">
<button onclick="document.querySelector('#result').textContent='updated'">Update</button><output id="result"></output></main>""",
    "blocking_overlays": """<main><h1>Workspace</h1><button onclick="document.querySelector('#result').textContent='saved'">Save</button><output id="result"></output></main>
<div id="cookie" style="position:fixed;inset:0;background:#000b;color:white;z-index:5">Cookie preferences <button onclick="this.parentElement.remove()">Accept</button></div>
<div id="newsletter" style="position:fixed;inset:20% 10%;background:white;color:black;z-index:6">Updates <button onclick="this.parentElement.remove()">Close</button></div>""",
    "spa_navigation": """<main><h1>Workspace</h1><div id="nav"><button data-page="records">Records</button><button data-page="settings">Settings</button></div><section id="view">Overview</section></main>
<script>document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{history.pushState({},'', '/' + b.dataset.page);document.querySelector('#view').textContent=b.dataset.page})</script>""",
    "late_hydration": """<main><h1>Overview</h1><section id="late">Loading</section></main>
<script>setTimeout(()=>{const b=document.createElement('button');b.textContent='Save changes';b.onclick=()=>b.textContent='Saved';document.querySelector('#late').replaceChildren(b)},3500)</script>""",
    "lazy_list": """<main><h1>Records</h1><ol id="items"></ol><p>Scroll to load more</p></main>
<script>let n=0;function add(){for(let i=0;i<10;i++){let li=document.createElement('li');li.textContent='Record '+(++n);document.querySelector('#items').append(li)}}add();onscroll=()=>{if(innerHeight+scrollY>=document.body.scrollHeight-20)add()}</script>""",
    "popups": """<main><h1>Resources</h1><a href="/opened" target="_blank">Open report</a><button onclick="window.open('/opened','_blank')">Open summary</button></main>""",
    "native_dialogs": """<main><h1>Confirmation</h1><button onclick="alert('Saved')">Show notice</button><button onclick="if(confirm('Continue?'))this.textContent='Confirmed'">Confirm action</button></main>""",
    "shadow_iframe": """<main><h1>Embedded controls</h1><sample-panel></sample-panel><iframe title="Embedded form" srcdoc="<form><h2>Feedback</h2><input placeholder='Comment'><button>Send</button></form>"></iframe></main>
<script>customElements.define('sample-panel',class extends HTMLElement{connectedCallback(){let r=this.attachShadow({mode:'open'});r.innerHTML='<button onclick="this.textContent=\'Added\'">Add item</button>'}})</script>""",
    "wizard": """<main><h1>Setup</h1><form id="form"><section id="step"><label>Title <input name="title" required></label><button>Next</button></section></form><output id="status"></output>
<script>const wizardForm=document.querySelector('#form');const wizardStep=document.querySelector('#step');const wizardStatus=document.querySelector('#status');wizardForm.onsubmit=e=>{e.preventDefault();wizardStep.innerHTML='<label>Category <input required></label><button>Finish</button>';wizardForm.onsubmit=e=>{e.preventDefault();wizardStatus.textContent='Setup complete'}};</script></main>""",
    "silent_failure": """<main><h1>Save record</h1><form><input name="value" placeholder="Value"><button>Save</button></form><output id="status"></output>
<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();await fetch('/api/save',{method:'POST'});status.textContent='Saved'}</script></main>""",
    "toast_success": """<main><h1>Save record</h1><form><input name="value" placeholder="Value"><button>Save</button></form><output id="status"></output>
<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();await fetch('/api/save',{method:'POST',body:new FormData(e.target)});status.textContent='Saved'}</script></main>""",
    "slow_flaky_api": """<main><h1>Submit request</h1><button id="send" onclick="fetch('/api/submit').then(r=>status.textContent=r.ok?'Complete':'Retry required')">Submit</button><output id="status"></output></main>""",
    "marketing_only": """<main><h1>Service overview</h1><p>Explore the available plans and features.</p><a href="/features">Features</a><a href="/contact">Contact</a></main>""",
    "authenticated_crud": """<main><h1>Records</h1><form id="login"><input placeholder="Email"><input type="password" placeholder="Password"><button>Sign in</button></form><section id="data" hidden><form><input placeholder="Record name"><button>Create</button></form><ul></ul></section>
<script>login.onsubmit=e=>{e.preventDefault();login.hidden=true;data.hidden=false};data.querySelector('form').onsubmit=e=>{e.preventDefault();let li=document.createElement('li');li.textContent=e.target.querySelector('input').value;data.querySelector('ul').append(li)}</script></main>""",
}


def make_app(pattern: str) -> FastAPI:
    app = FastAPI()
    calls = 0
    saved_records: list[str] = []

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(PAGES[pattern])

    @app.get("/opened", response_class=HTMLResponse)
    async def opened():
        return HTMLResponse("<main><h1>Opened report</h1><p>Report content</p></main>")

    @app.get("/{section}", response_class=HTMLResponse)
    async def section(section: str):
        return HTMLResponse(f"<main><h1>{section.title()}</h1></main>")

    @app.get("/api/records")
    async def records():
        return {"records": list(saved_records)}

    @app.post("/api/{action}")
    async def action(action: str):
        nonlocal calls
        calls += 1
        if pattern == "slow_flaky_api":
            await asyncio.sleep(3)
            if calls == 1:
                return JSONResponse({"saved": False}, status_code=503)
        if pattern == "toast_success":
            saved_records.append(f"record-{calls}")
            return {"saved": True, "count": len(saved_records)}
        if pattern == "silent_failure":
            return {"saved": False, "count": len(saved_records)}
        return {"ok": True}

    return app
