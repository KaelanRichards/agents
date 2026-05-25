# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.110", "uvicorn>=0.30"]
# ///
"""webdash — live HTML control center for the agent environment (FastAPI, single-file via uv).

Live status via SSE, streamed action logs, embedded Grafana, real cost, and a control plane
(sync / doctor / provision / teardown / reboot / MCP add+remove).

Security: binds to 127.0.0.1 by default and runs shell commands. To reach it from elsewhere
(e.g. a Tailscale tailnet) set WEBDASH_HOST=<tailnet-ip> AND WEBDASH_TOKEN=<secret>; never bind
0.0.0.0 without a token. For a quick phone view, SSH-tunnel the port instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

REPO = os.environ.get("AGENTS_REPO_SLUG", "KaelanRichards/agents")
PORT = int(os.environ.get("WEBDASH_PORT", "8787"))
HOST = os.environ.get("WEBDASH_HOST", "127.0.0.1")
TOKEN = os.environ.get("WEBDASH_TOKEN", "")
GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000")
TTYD = os.environ.get("TTYD_URL", "http://localhost:7681")

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

# Rough monthly price per Hetzner type (EUR), for the cost readout.
PRICES = {"cax11": 3.79, "cax21": 6.49, "cax31": 12.49, "cpx21": 7.05, "cpx31": 13.10}

PANELS: dict[str, tuple[str, str]] = {
    "machines": (
        "Machines",
        "hcloud server list 2>/dev/null || echo '(set HCLOUD_TOKEN)'",
    ),
    "health": ("Health", "agents-doctor 2>/dev/null | tail -1"),
    "mcp": ("MCP servers", "mcp-sync list 2>/dev/null"),
    "ci": (
        "Repo / CI",
        f"gh run list --repo {REPO} -L 5 2>/dev/null | cut -f1-4; "
        f"echo '--- open PRs ---'; gh pr list --repo {REPO} 2>/dev/null || echo none",
    ),
    "sessions": ("Sessions", "tmux ls 2>/dev/null || echo '(none)'"),
}


def sh(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV
        )
        return (r.stdout or r.stderr or "(no output)").strip()
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def monthly_cost() -> str:
    try:
        out = subprocess.run(
            "hcloud server list -o json",
            shell=True,
            capture_output=True,
            text=True,
            timeout=20,
            env=ENV,
        ).stdout
        servers = json.loads(out or "[]")
        total = sum(
            PRICES.get(s.get("server_type", {}).get("name", ""), 0.0) for s in servers
        )
        return f"{len(servers)} server(s) · ~EUR {total:.2f}/mo"
    except Exception:  # noqa: BLE001
        return "(set HCLOUD_TOKEN for cost)"


def status_payload() -> dict:
    data = {pid: {"title": t, "out": sh(c)} for pid, (t, c) in PANELS.items()}
    data["cost"] = {"title": "Cost", "out": monthly_cost()}
    return data


# action -> builds an argv-safe shell command from posted args
def _cmd_for(action: str, args: dict) -> str | None:
    name = shlex.quote(str(args.get("name", "")))
    cmd = str(args.get("command", ""))
    server = shlex.quote(str(args.get("server", "agents")))
    builders = {
        "sync": lambda: "mcp-sync && agents-sync",
        "doctor": lambda: "agents-doctor",
        "provision": lambda: "bash ~/.config/agents/provision.sh",
        "teardown": lambda: "bash ~/.config/agents/teardown.sh -y",
        "reboot": lambda: f"hcloud server reboot {server}",
        "mcp-add": lambda: (
            f"mcp-sync add {name} -- {cmd}" if args.get("name") and cmd else None
        ),
        "mcp-remove": lambda: f"mcp-sync remove {name}" if args.get("name") else None,
    }
    b = builders.get(action)
    return b() if b else None


app = FastAPI(title="agents webdash")


@app.middleware("http")
async def auth(request: Request, call_next):
    if not TOKEN:
        return await call_next(request)
    via_param = request.query_params.get("token") or request.headers.get("x-token")
    tok = via_param or request.cookies.get("token")
    if tok != TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    response = await call_next(request)
    # Authenticated via ?token= / header -> set a cookie so the bare URL works next time.
    if via_param == TOKEN and request.cookies.get("token") != TOKEN:
        response.set_cookie(
            "token", TOKEN, max_age=2592000, httponly=True, samesite="lax", secure=True
        )
    return response


@app.get("/api/status")
def status() -> JSONResponse:
    return JSONResponse(status_payload())


@app.get("/api/events")
async def events() -> StreamingResponse:
    async def gen():
        while True:
            payload = await asyncio.to_thread(status_payload)
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(10)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/run")
async def run(body: dict) -> StreamingResponse:
    action = str(body.get("action", ""))
    cmd = _cmd_for(action, body.get("args", {}) or {})
    if not cmd:
        raise HTTPException(400, f"unknown or incomplete action: {action}")

    async def gen():
        yield f"$ {cmd}\n"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=ENV,
        )
        assert proc.stdout
        async for line in proc.stdout:
            yield line.decode(errors="replace")
        await proc.wait()
        yield f"\n[exit {proc.returncode}]\n"

    return StreamingResponse(gen(), media_type="text/plain")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX.replace("__GRAFANA__", GRAFANA).replace("__TTYD__", TTYD)


INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>agents · webdash</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 ui-monospace,Menlo,monospace;background:#0d1117;color:#c9d1d9}
header{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;padding:.6rem 1rem;background:#161b22;border-bottom:1px solid #30363d;position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0 .5rem 0 0;font-weight:700}
button{font:inherit;background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:.3rem .6rem;cursor:pointer}
button:hover{background:#30363d}
button.danger{border-color:#7d2b2b}
#updated{margin-left:auto;color:#8b949e;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:1rem;padding:1rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:.6rem .9rem;overflow:auto;max-height:340px}
.card h2{font-size:13px;margin:0 0 .4rem;color:#58a6ff}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font-size:12.5px}
iframe{width:100%;height:340px;border:1px solid #30363d;border-radius:8px;background:#000}
.full{grid-column:1/-1}
form{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 0}
input{font:inherit;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:.3rem .5rem;flex:1;min-width:120px}
#log{position:fixed;bottom:0;left:0;right:0;height:38vh;background:#010409;border-top:2px solid #1f6feb;padding:.5rem 1rem;overflow:auto;transform:translateY(100%);transition:.25s;z-index:10}
#log.open{transform:translateY(0)}
#log pre{font-size:12px}
#logbar{position:fixed;bottom:.5rem;right:1rem;z-index:11}
</style></head><body>
<header>
  <h1>agents · webdash</h1>
  <button onclick="run('sync')">⇄ Sync</button>
  <button onclick="run('doctor')">🩺 Doctor</button>
  <button onclick="run('provision')">＋ Provision</button>
  <button class="danger" onclick="if(confirm('Tear down the VM (snapshot+delete)?'))run('teardown')">🗑 Teardown</button>
  <button class="danger" onclick="if(confirm('Reboot the VM?'))run('reboot')">⟳ Reboot</button>
  <span id="updated">connecting…</span>
</header>
<div class="grid" id="grid"></div>
<div class="grid">
  <div class="card"><h2>Add MCP server</h2>
    <form onsubmit="mcpAdd(event)">
      <input id="mname" placeholder="name"><input id="mcmd" placeholder="npx -y pkg">
      <button>add</button>
    </form>
    <form onsubmit="mcpRemove(event)" style="margin-top:.3rem">
      <input id="mrm" placeholder="remove name"><button class="danger">remove</button>
    </form>
  </div>
</div>
<h2 style="padding:0 1rem;color:#58a6ff">Grafana</h2>
<div style="padding:0 1rem 1rem"><iframe src="__GRAFANA__" class="full"></iframe></div>
<h2 style="padding:0 1rem;color:#58a6ff">Terminal (ttyd)</h2>
<div style="padding:0 1rem 6rem"><iframe src="__TTYD__" class="full" style="height:420px"></iframe></div>
<div id="logbar"><button onclick="document.getElementById('log').classList.toggle('open')">▤ Log</button></div>
<div id="log"><pre id="logpre"></pre></div>
<script>
const TOKEN=new URLSearchParams(location.search).get('token')||'';
const auth=u=>TOKEN?u+(u.includes('?')?'&':'?')+'token='+TOKEN:u;
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function render(d){
  const order=['machines','cost','health','mcp','ci','sessions'];
  document.getElementById('grid').innerHTML=order.filter(k=>d[k]).map(k=>
    `<div class="card"><h2>${esc(d[k].title)}</h2><pre>${esc(d[k].out)}</pre></div>`).join('');
  document.getElementById('updated').textContent='live · '+new Date().toLocaleTimeString();
}
const ev=new EventSource(auth('/api/events'));
ev.onmessage=e=>render(JSON.parse(e.data));
ev.onerror=()=>document.getElementById('updated').textContent='reconnecting…';
function openLog(){const l=document.getElementById('log');l.classList.add('open');return document.getElementById('logpre');}
async function run(action,args={}){
  const pre=openLog();pre.textContent='';
  const r=await fetch(auth('/api/run'),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,args})});
  const rd=r.body.getReader(),dec=new TextDecoder();
  for(;;){const{value,done}=await rd.read();if(done)break;pre.textContent+=dec.decode(value);document.getElementById('log').scrollTop=1e9;}
}
function mcpAdd(e){e.preventDefault();run('mcp-add',{name:mname.value,command:mcmd.value});}
function mcpRemove(e){e.preventDefault();run('mcp-remove',{name:mrm.value});}
</script></body></html>"""


if __name__ == "__main__":
    note = f"http://{HOST}:{PORT}" + ("  (token required)" if TOKEN else "")
    print(f"webdash on {note}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
