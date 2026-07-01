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
import secrets
import shlex
import subprocess
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

REPO = os.environ.get("AGENTS_REPO_SLUG", "KaelanRichards/agents")
PORT = int(os.environ.get("WEBDASH_PORT", "8787"))
HOST = os.environ.get("WEBDASH_HOST", "127.0.0.1")
TOKEN = os.environ.get("WEBDASH_TOKEN", "")
GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000")
TTYD = os.environ.get("TTYD_URL", "http://localhost:7681")
CSRF_COOKIE = "webdash_csrf"
CSRF_TOKEN = secrets.token_urlsafe(32)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

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
    "control": (
        "Agent Control",
        "agent-profile list 2>/dev/null | sed 's/^/profile: /'; "
        "agent-ledger list --limit 5 2>/dev/null | sed 's/^/run: /' || true; "
        "agent-approve list --limit 5 2>/dev/null | sed 's/^/approval: /' || true",
    ),
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
    item_id = shlex.quote(str(args.get("id", "")))
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
        "profile-compile": lambda: "agent-profile validate && agent-profile compile",
        "approval-approve": lambda: (
            f"agent-approve approve {item_id}" if args.get("id") else None
        ),
        "approval-reject": lambda: (
            f"agent-approve reject {item_id}" if args.get("id") else None
        ),
    }
    b = builders.get(action)
    return b() if b else None


app = FastAPI(title="agents webdash")


def _host_only(value: str) -> str:
    host = (value or "").split(",", 1)[0].strip()
    if "://" in host:
        host = urlparse(host).netloc
    if host.startswith("["):
        return host.split("]", 1)[0].lstrip("[").lower()
    return host.split(":", 1)[0].lower()


def _same_origin(request: Request) -> bool:
    host = _host_only(request.headers.get("host", ""))
    for header in ("origin", "referer"):
        value = request.headers.get(header, "")
        if not value:
            continue
        if _host_only(value) != host:
            return False
    return True


def _require_run_auth(request: Request) -> None:
    if not TOKEN:
        raise HTTPException(
            403, "WEBDASH_TOKEN is required for mutating dashboard actions"
        )
    if not _same_origin(request):
        raise HTTPException(403, "cross-origin dashboard action denied")
    csrf_header = request.headers.get("x-csrf-token", "")
    csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
    if csrf_header != CSRF_TOKEN or csrf_cookie != CSRF_TOKEN:
        raise HTTPException(403, "CSRF token missing or invalid")


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
    secure_cookie = request.url.scheme == "https"
    if via_param == TOKEN and request.cookies.get("token") != TOKEN:
        response.set_cookie(
            "token",
            TOKEN,
            max_age=2592000,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
        )
    if request.cookies.get(CSRF_COOKIE) != CSRF_TOKEN:
        response.set_cookie(
            CSRF_COOKIE,
            CSRF_TOKEN,
            max_age=2592000,
            httponly=False,
            samesite="strict",
            secure=secure_cookie,
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
async def run(request: Request, body: dict) -> StreamingResponse:
    _require_run_auth(request)
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


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>agents control</title>
<style>
:root{
  color-scheme:light;
  --paper:#f4f6f3;--ink:#171916;--muted:#667064;--line:#c9d1c4;--panel:#ffffff;
  --panel2:#eef2ec;--green:#16784f;--red:#b3261e;--amber:#a35d00;--blue:#2359a7;
  --shadow:0 16px 38px rgba(30,39,28,.12)
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 Avenir Next,Segoe UI,Helvetica,sans-serif;letter-spacing:0}
button,input,select,textarea{font:inherit}
button{border:1px solid #9aa694;background:#fff;color:var(--ink);border-radius:6px;padding:.48rem .7rem;cursor:pointer;min-height:34px}
button:hover{background:#eaf0e7}
button.primary{background:var(--ink);color:#fff;border-color:var(--ink)}
button.danger{color:var(--red);border-color:#d8aaa6;background:#fff8f7}
button.ghost{background:transparent}
input,select,textarea{border:1px solid #aeb8a9;border-radius:6px;background:#fff;color:var(--ink);padding:.48rem .6rem;min-height:34px;width:100%}
textarea{min-height:84px;resize:vertical}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font:12px/1.45 SFMono-Regular,Menlo,Consolas,monospace}
.app{display:grid;grid-template-columns:246px 1fr;min-height:100vh}
.rail{background:#18201a;color:#f5f7f1;padding:18px 14px;display:flex;flex-direction:column;gap:18px;position:sticky;top:0;height:100vh}
.brand{border-bottom:1px solid rgba(255,255,255,.16);padding-bottom:16px}
.brand b{display:block;font-size:18px;letter-spacing:.02em}.brand span{color:#aebba9;font-size:12px}
.nav{display:grid;gap:6px}.nav button{text-align:left;background:transparent;color:#e9efe5;border-color:transparent}.nav button.active,.nav button:hover{background:#2b352d;border-color:#465243}
.railFoot{margin-top:auto;color:#aebba9;font-size:12px}
.main{min-width:0}
.top{position:sticky;top:0;z-index:4;background:rgba(244,246,243,.92);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:14px 20px;display:flex;gap:12px;align-items:center}
.top h1{font-size:20px;margin:0;min-width:0;flex:1}.updated{color:var(--muted);font-size:12px;white-space:nowrap}
.toolbar{display:flex;gap:8px;flex-wrap:wrap}.section{display:none;padding:20px;max-width:1540px}.section.active{display:block}
.hero{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}
.metric{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;box-shadow:var(--shadow);min-height:94px}
.metric label{display:block;font-size:11px;text-transform:uppercase;color:var(--muted);font-weight:700}.metric strong{display:block;font-size:25px;margin-top:8px}.metric small{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.span4{grid-column:span 4}.span5{grid-column:span 5}.span6{grid-column:span 6}.span7{grid-column:span 7}.span8{grid-column:span 8}.span12{grid-column:1/-1}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow);min-width:0;overflow:hidden}
.panelHead{display:flex;align-items:center;gap:10px;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--line);background:var(--panel2)}
.panelHead h2{font-size:14px;margin:0}.panelBody{padding:14px;overflow:auto}.scroll{max-height:360px}
.status{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:3px 9px;font-size:12px;background:#fff}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}.ok .dot{background:var(--green)}.warn .dot{background:var(--amber)}.bad .dot{background:var(--red)}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-size:11px;text-transform:uppercase;border-bottom:1px solid var(--line);padding:7px}td{border-bottom:1px solid #e4e9e1;padding:8px;vertical-align:top}tr:last-child td{border-bottom:0}
.mono{font-family:SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}.muted{color:var(--muted)}.clip{max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.formGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.formGrid .wide{grid-column:1/-1}
.tabs{display:flex;gap:6px;margin-bottom:12px}.tabs button{background:#fff}.tabs button.active{background:var(--ink);color:#fff;border-color:var(--ink)}
iframe{width:100%;height:540px;border:0;background:#111;border-radius:0}.terminalFrame{height:560px}
.drawer{position:fixed;right:18px;bottom:18px;width:min(760px,calc(100vw - 36px));height:min(520px,70vh);background:#10140f;color:#e9efe5;border:1px solid #4e594a;border-radius:8px;box-shadow:0 24px 80px rgba(0,0,0,.35);transform:translateY(18px);opacity:0;visibility:hidden;pointer-events:none;transition:.2s;z-index:9;display:flex;flex-direction:column}
.drawer.open{transform:translateY(0);opacity:1;visibility:visible;pointer-events:auto}.drawerHead{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid #374132}.drawer pre{padding:12px;overflow:auto;flex:1;color:#e9efe5}
.empty{color:var(--muted);padding:12px;border:1px dashed var(--line);border-radius:6px;background:#fafbf8}
@media (max-width:980px){.app{grid-template-columns:1fr}.rail{position:relative;height:auto}.hero{grid-template-columns:repeat(2,1fr)}.span4,.span5,.span6,.span7,.span8{grid-column:1/-1}.top{align-items:flex-start;flex-direction:column}.formGrid{grid-template-columns:1fr}}
@media (max-width:560px){.hero{grid-template-columns:1fr}.section{padding:12px}.toolbar button{flex:1}}
</style></head><body>
<div class="app">
  <aside class="rail">
    <div class="brand"><b>agents</b><span>local control plane</span></div>
    <nav class="nav">
      <button class="active" data-view="overview" onclick="showView('overview')">Overview</button>
      <button data-view="work" onclick="showView('work')">Work Queue</button>
      <button data-view="config" onclick="showView('config')">Config</button>
      <button data-view="observability" onclick="showView('observability')">Observability</button>
    </nav>
    <div class="railFoot"><div id="railStatus">connecting</div><div id="railRepo">KaelanRichards/agents</div></div>
  </aside>
  <main class="main">
    <header class="top">
      <h1 id="viewTitle">Overview</h1>
      <div class="toolbar">
        <button onclick="run('sync')">Sync</button>
        <button onclick="run('doctor')">Doctor</button>
        <button onclick="run('profile-compile')">Profiles</button>
        <button class="danger" onclick="if(confirm('Reboot the agents VM?'))run('reboot')">Reboot VM</button>
      </div>
      <div class="updated" id="updated">connecting</div>
    </header>

    <section id="overview" class="section active">
      <div class="hero" id="hero"></div>
      <div class="grid">
        <article class="panel span7"><div class="panelHead"><h2>Queue</h2></div><div class="panelBody scroll" id="queueTable"></div></article>
        <article class="panel span5"><div class="panelHead"><h2>Approvals</h2><span id="approvalBadge" class="status"></span></div><div class="panelBody scroll" id="approvalTable"></div></article>
        <article class="panel span6"><div class="panelHead"><h2>CI</h2></div><div class="panelBody scroll" id="ciTable"></div></article>
        <article class="panel span6"><div class="panelHead"><h2>Machines</h2></div><div class="panelBody scroll" id="machinesTable"></div></article>
      </div>
    </section>

    <section id="work" class="section">
      <div class="grid">
        <article class="panel span7"><div class="panelHead"><h2>Queue State</h2></div><div class="panelBody scroll" id="queueTableFull"></div></article>
        <article class="panel span6"><div class="panelHead"><h2>Approval Inbox</h2></div><div class="panelBody scroll" id="approvalTableFull"></div></article>
        <article class="panel span6"><div class="panelHead"><h2>Decide Approval</h2></div><div class="panelBody">
          <form onsubmit="approvalApprove(event)" class="formGrid"><input id="aidApprove" class="wide" placeholder="approval id"><button class="primary">Approve</button></form>
          <form onsubmit="approvalReject(event)" class="formGrid" style="margin-top:10px"><input id="aidReject" class="wide" placeholder="approval id"><button class="danger">Reject</button></form>
        </div></article>
      </div>
    </section>

    <section id="config" class="section">
      <div class="grid">
        <article class="panel span5"><div class="panelHead"><h2>Profiles</h2></div><div class="panelBody scroll" id="profilesTable"></div></article>
        <article class="panel span7"><div class="panelHead"><h2>MCP Servers</h2></div><div class="panelBody scroll" id="mcpTable"></div></article>
        <article class="panel span6"><div class="panelHead"><h2>Add MCP Server</h2></div><div class="panelBody">
          <form onsubmit="mcpAdd(event)" class="formGrid"><input id="mname" placeholder="name"><input id="mcmd" placeholder="npx -y package"><button class="primary">Add server</button></form>
        </div></article>
        <article class="panel span6"><div class="panelHead"><h2>Remove MCP Server</h2></div><div class="panelBody">
          <form onsubmit="mcpRemove(event)" class="formGrid"><input id="mrm" class="wide" placeholder="server name"><button class="danger">Remove server</button></form>
        </div></article>
        <article class="panel span12"><div class="panelHead"><h2>Raw Health</h2></div><div class="panelBody scroll"><pre id="healthRaw"></pre></div></article>
      </div>
    </section>

    <section id="observability" class="section">
      <div class="tabs"><button class="active" onclick="showConsole('grafana')">Grafana</button><button onclick="showConsole('terminal')">Terminal</button></div>
      <article id="grafanaPane" class="panel"><iframe src="__GRAFANA__"></iframe></article>
      <article id="terminalPane" class="panel" style="display:none"><iframe class="terminalFrame" src="__TTYD__"></iframe></article>
    </section>
  </main>
</div>
<div class="drawer" id="drawer"><div class="drawerHead"><b id="drawerTitle">Command output</b><button onclick="closeDrawer()">Close</button></div><pre id="logpre"></pre></div>
	<script>
	const TOKEN=new URLSearchParams(location.search).get('token')||'';
	const auth=u=>TOKEN?u+(u.includes('?')?'&':'?')+'token='+TOKEN:u;
	const cookie=n=>document.cookie.split('; ').find(x=>x.startsWith(n+'='))?.split('=').slice(1).join('=')||'';
	const esc=s=>String(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let state={};
function lines(k){return ((state[k]&&state[k].out)||'').split('\\n').filter(Boolean)}
function classify(text){text=String(text||'').toLowerCase();if(text.includes('fail')||text.includes('error'))return'bad';if(text.includes('warn')||text.includes('pending'))return'warn';return'ok'}
function showView(id){document.querySelectorAll('.section').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===id));viewTitle.textContent={overview:'Overview',work:'Work Queue',config:'Config',observability:'Observability'}[id]||id}
function showConsole(id){grafanaPane.style.display=id==='grafana'?'block':'none';terminalPane.style.display=id==='terminal'?'block':'none';document.querySelectorAll('.tabs button').forEach((b,i)=>b.classList.toggle('active',(id==='grafana'&&i===0)||(id==='terminal'&&i===1)))}
function metric(label,value,detail,kind='ok'){return `<div class="metric ${kind}"><label>${esc(label)}</label><strong>${esc(value)}</strong><small>${esc(detail)}</small></div>`}
function statusPill(text,kind){return `<span class="status ${kind}"><span class="dot"></span>${esc(text)}</span>`}
function table(headers,rows){if(!rows.length)return'<div class="empty">No items</div>';return `<table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`}
function isRow(p){return /^\\d{4}-\\d{2}-\\d{2}T/.test(p[0]||'')}
function parseQueue(){return lines('control').filter(l=>l.startsWith('queue: ')).map(l=>l.replace('queue: ','').split('\\t')).filter(isRow)}
function parseApprovals(){return lines('control').filter(l=>l.startsWith('approval: ')).map(l=>l.replace('approval: ','').split('\\t')).filter(isRow)}
function parseRuns(){return lines('control').filter(l=>l.startsWith('run: ')).map(l=>l.replace('run: ','').split('\\t')).filter(isRow)}
function parseProfiles(){return lines('control').filter(l=>l.startsWith('profile: ')).map(l=>l.replace('profile: ','').split('\\t'))}
function parseMcp(){return lines('mcp').map(l=>l.trim()).filter(Boolean).map(l=>l.replace(/^/,'').split(/\\s{2,}/))}
function parseCi(){return lines('ci').filter(l=>!l.startsWith('---')).map(l=>l.split('\\t')).filter(p=>p.length>2)}
function renderHero(){
  const health=(state.health&&state.health.out)||'unknown';
  const machines=lines('machines').filter(l=>/^\\s*\\d+/.test(l)).length;
  const queue=parseQueue(), approvals=parseApprovals(), runs=parseRuns();
  hero.innerHTML=[
    metric('Health',health.includes('HEALTHY')?'Healthy':'Check',health,classify(health)),
    metric('Machines',machines||'0',(state.cost&&state.cost.out)||'',machines?'ok':'warn'),
    metric('Queue',String(queue.length),queue.filter(q=>q[2]==='running').length+' running',queue.some(q=>q[2]==='failed')?'bad':'ok'),
    metric('Approvals',String(approvals.filter(a=>a[2]==='pending').length),runs.length+' recent runs',approvals.length?'warn':'ok')
  ].join('');
  approvalBadge.innerHTML=statusPill(approvals.filter(a=>a[2]==='pending').length+' pending',approvals.length?'warn':'ok');
}
function renderQueue(target){
  const rows=parseQueue().map(p=>`<tr><td class="mono">${esc((p[1]||'').slice(0,8))}</td><td>${statusPill(p[2]||'',classify(p[2]))}</td><td>${esc(p[3]||'')}</td><td>${esc(p[4]||'')}</td><td class="clip">${esc(p[6]||'')}</td></tr>`);
  target.innerHTML=table(['id','status','profile','agent','task'],rows);
}
function renderApprovals(target){
  const rows=parseApprovals().map(p=>`<tr><td class="mono">${esc((p[1]||'').slice(0,8))}</td><td>${statusPill(p[2]||'',classify(p[2]))}</td><td>${esc(p[3]||'')}</td><td class="clip">${esc(p[4]||'')}</td></tr>`);
  target.innerHTML=table(['id','status','kind','summary'],rows);
}
function renderConfig(){
  profilesTable.innerHTML=table(['profile','risk','description'],parseProfiles().map(p=>`<tr><td>${esc(p[0])}</td><td>${statusPill(p[1]||'',p[1]==='critical'||p[1]==='high'?'warn':'ok')}</td><td>${esc(p[2]||'')}</td></tr>`));
  mcpTable.innerHTML=table(['server','type','target'],parseMcp().map(p=>`<tr><td>${esc((p[0]||'').replace(':',''))}</td><td>${esc(p[1]||'')}</td><td class="clip">${esc(p[2]||'')}</td></tr>`));
  healthRaw.textContent=(state.health&&state.health.out)||'';
}
function renderCiMachines(){
  ciTable.innerHTML=table(['state','result','title','workflow'],parseCi().map(p=>`<tr><td>${esc(p[0])}</td><td>${statusPill(p[1]||'',classify(p[1]))}</td><td class="clip">${esc(p[2]||'')}</td><td>${esc(p[3]||'')}</td></tr>`));
  machinesTable.innerHTML=table(['raw'],lines('machines').map(l=>`<tr><td class="mono">${esc(l)}</td></tr>`));
}
function render(d){
  state=d;renderHero();renderQueue(queueTable);renderQueue(queueTableFull);renderApprovals(approvalTable);renderApprovals(approvalTableFull);renderConfig();renderCiMachines();
  updated.textContent='updated '+new Date().toLocaleTimeString();railStatus.textContent=(d.health&&d.health.out)||'unknown';
}
const ev=new EventSource(auth('/api/events'));
ev.onmessage=e=>render(JSON.parse(e.data));
ev.onerror=()=>updated.textContent='reconnecting';
function openDrawer(title){drawer.classList.add('open');drawerTitle.textContent=title||'Command output';logpre.textContent='';return logpre}
function closeDrawer(){drawer.classList.remove('open')}
	async function run(action,args={}){
	  const pre=openDrawer(action);
	  const r=await fetch(auth('/api/run'),{method:'POST',headers:{'content-type':'application/json','x-csrf-token':cookie('webdash_csrf')},body:JSON.stringify({action,args})});
	  if(!r.ok){pre.textContent=await r.text();return}
  const rd=r.body.getReader(),dec=new TextDecoder();
  for(;;){const{value,done}=await rd.read();if(done)break;pre.textContent+=dec.decode(value);pre.scrollTop=pre.scrollHeight}
}
function mcpAdd(e){e.preventDefault();run('mcp-add',{name:mname.value,command:mcmd.value})}
function mcpRemove(e){e.preventDefault();run('mcp-remove',{name:mrm.value})}
function approvalApprove(e){e.preventDefault();run('approval-approve',{id:aidApprove.value})}
function approvalReject(e){e.preventDefault();run('approval-reject',{id:aidReject.value})}
</script></body></html>"""


if __name__ == "__main__":
    if _host_only(HOST) not in LOCAL_HOSTS and not TOKEN:
        raise SystemExit("WEBDASH_TOKEN is required when WEBDASH_HOST is not localhost")
    note = f"http://{HOST}:{PORT}" + ("  (token required)" if TOKEN else "")
    print(f"webdash on {note}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
