# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.110", "uvicorn>=0.30"]
# ///
"""webdash — native HTML control center for the agent environment (FastAPI, single-file via uv).

Binds to 127.0.0.1 only (it runs shell commands — do NOT expose it). For phone access,
SSH-tunnel the port:  ssh -L 8787:localhost:8787 you@host  then open http://localhost:8787
"""

from __future__ import annotations

import os
import subprocess

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

REPO = os.environ.get("AGENTS_REPO_SLUG", "KaelanRichards/agents")
PORT = int(os.environ.get("WEBDASH_PORT", "8787"))

_PATH = ":".join(
    [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.local/share/mise/shims"),
        os.path.expanduser("~/.cargo/bin"),
        "/opt/homebrew/bin",
        "/home/linuxbrew/.linuxbrew/bin",
        os.environ.get("PATH", ""),
    ]
)
ENV = {**os.environ, "PATH": _PATH}

PANELS: dict[str, tuple[str, str]] = {
    "machines": (
        "Machines (Hetzner)",
        "hcloud server list 2>/dev/null || echo '(set HCLOUD_TOKEN)'",
    ),
    "health": ("Health", "agents-doctor 2>/dev/null | tail -1"),
    "mcp": ("MCP servers", "mcp-sync list 2>/dev/null"),
    "ci": (
        "Repo / CI",
        f"gh run list --repo {REPO} -L 5 2>/dev/null | cut -f1-4; "
        f"echo '--- open PRs ---'; gh pr list --repo {REPO} 2>/dev/null || echo none",
    ),
    "sessions": ("Sessions (tmux)", "tmux ls 2>/dev/null || echo '(none)'"),
}
ACTIONS: dict[str, str] = {
    "sync": "mcp-sync && agents-sync 2>&1 | tail -4",
    "doctor": "agents-doctor 2>&1 | tail -1",
}


def sh(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV
        )
        return (r.stdout or r.stderr or "(no output)").strip()
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


app = FastAPI(title="agents webdash")


@app.get("/api/status")
def status() -> JSONResponse:
    return JSONResponse(
        {pid: {"title": t, "out": sh(c)} for pid, (t, c) in PANELS.items()}
    )


@app.post("/api/action/{name}")
def action(name: str) -> JSONResponse:
    cmd = ACTIONS.get(name)
    if not cmd:
        return JSONResponse({"error": f"unknown action: {name}"}, status_code=404)
    return JSONResponse({"out": sh(cmd, timeout=120)})


INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>agents · webdash</title><style>
:root{color-scheme:dark}
body{margin:0;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#0d1117;color:#c9d1d9}
header{display:flex;gap:.75rem;align-items:center;padding:.7rem 1rem;background:#161b22;border-bottom:1px solid #30363d;position:sticky;top:0}
header h1{font-size:15px;margin:0;font-weight:700}
button{font:inherit;background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:.35rem .7rem;cursor:pointer}
button:hover{background:#30363d}
#updated{margin-left:auto;color:#8b949e;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:1rem;padding:1rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:.6rem .9rem;overflow:auto}
.card h2{font-size:13px;margin:0 0 .4rem;color:#58a6ff}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font-size:12.5px}
#toast{position:fixed;bottom:1rem;right:1rem;background:#1f6feb;color:#fff;padding:.5rem .9rem;border-radius:6px;opacity:0;transition:opacity .3s}
</style></head><body>
<header>
  <h1>agents · webdash</h1>
  <button onclick="load()">↻ Refresh</button>
  <button onclick="act('sync')">⇄ Sync</button>
  <button onclick="act('doctor')">🩺 Doctor</button>
  <button onclick="window.open('http://localhost:3000','_blank')">📊 Grafana</button>
  <span id="updated">…</span>
</header>
<div class="grid" id="grid"></div>
<div id="toast"></div>
<script>
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.opacity=1;setTimeout(()=>t.style.opacity=0,3500);}
async function load(){
  try{
    const d=await (await fetch('/api/status')).json();
    document.getElementById('grid').innerHTML=Object.values(d).map(p=>
      `<div class="card"><h2>${esc(p.title)}</h2><pre>${esc(p.out)}</pre></div>`).join('');
    document.getElementById('updated').textContent='updated '+new Date().toLocaleTimeString();
  }catch(e){toast('refresh failed');}
}
async function act(n){
  toast(n+'…');
  try{const d=await (await fetch('/api/action/'+n,{method:'POST'})).json();
    toast((d.out||d.error||'done').split('\\n').pop());load();}
  catch(e){toast(n+' failed');}
}
load();setInterval(load,15000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX


if __name__ == "__main__":
    print(
        f"webdash on http://127.0.0.1:{PORT}  (phone: ssh -L {PORT}:localhost:{PORT} you@host)"
    )
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
