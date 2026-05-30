# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.110", "uvicorn>=0.30"]
# ///
"""agentd — typed control-plane daemon for the agent environment (FastAPI, single-file via uv).

This is the single backend the desktop app, `dashweb`, and the remote VM all talk to. Unlike the
older dashboards it does NOT screen-scrape its own CLIs: it imports `scripts/agent_control.py`
as a library and returns structured JSON for profiles / ledger / approvals / queue / evals, and
tails `state/events.jsonl` as a live Server-Sent-Events feed. Only genuinely external tools
(`hcloud`, `agents-doctor`, `mcp-sync`, `agents-sync`) are shelled out, and only once.

Security mirrors `dashweb`: binds 127.0.0.1 by default and runs shell commands for mutations.
To reach it from a tailnet set AGENTD_HOST=<tailnet-ip> AND AGENTD_TOKEN=<secret>; never bind
0.0.0.0 without a token. Mutations additionally require a same-origin CSRF header. Reads are
open on localhost (parity with dashweb) but gated by the token when one is set.

Run:  agentd            # http://127.0.0.1:8788
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

AH = Path(
    os.environ.get("AGENTS_HOME", str(Path.home() / ".config/agents"))
).expanduser()
sys.path.insert(0, str(AH / "scripts"))
import agent_control as ac  # noqa: E402  (path set above)

REPO = os.environ.get("AGENTS_REPO_SLUG", "KaelanRichards/agents")
PORT = int(os.environ.get("AGENTD_PORT", "8788"))
HOST = os.environ.get("AGENTD_HOST", "127.0.0.1")
TOKEN = os.environ.get("AGENTD_TOKEN", "")
CSRF_COOKIE = "agentd_csrf"
CSRF_TOKEN = secrets.token_urlsafe(32)

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

# Rough monthly price per Hetzner type (EUR), for the cost readout (matches dashweb).
PRICES = {"cax11": 3.79, "cax21": 6.49, "cax31": 12.49, "cpx21": 7.05, "cpx31": 13.10}


def sh(cmd: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV
        )
        return r.returncode, (r.stdout or r.stderr or "").strip()
    except Exception as e:  # noqa: BLE001
        return 1, f"error: {e}"


# ---------------------------------------------------------------------------
# Read model — control-plane data straight from the imported library.
# ---------------------------------------------------------------------------


def fleet() -> dict:
    # Fast path: hcloud (~1s) + in-process ledger check only, so the default panel renders almost
    # instantly. agents-doctor (~4-6s) is NOT called here — it's fetched lazily via /api/doctor
    # after the panel paints, so a slow check never makes the window look frozen.
    code, out = sh("hcloud server list -o json 2>/dev/null", 8)
    servers: list[dict] = []
    total = 0.0
    if code == 0 and out:
        try:
            for s in json.loads(out):
                name = s.get("server_type", {}).get("name", "")
                price = PRICES.get(name, 0.0)
                total += price
                servers.append(
                    {
                        "name": s.get("name", ""),
                        "type": name,
                        "status": s.get("status", ""),
                        "ip": (s.get("public_net", {}).get("ipv4") or {}).get("ip", ""),
                        "price_eur": price,
                    }
                )
        except (json.JSONDecodeError, TypeError):
            pass
    chain = ac.verify_ledger()
    return {
        "servers": servers,
        "monthly_eur": round(total, 2),
        "ledger_ok": bool(chain.get("ok")),
        "ledger_checked": chain.get("checked", 0),
    }


def doctor() -> dict:
    """agents-doctor's one-line summary — slow (~4-6s), so the Fleet panel fetches it separately."""
    _, line = sh("agents-doctor 2>/dev/null | tail -1", 15)
    return {"doctor": line or "(agents-doctor unavailable)"}


def mcp_servers() -> list[dict]:
    canon = AH / "mcp.json"
    if not canon.exists():
        return []
    data = ac.load_json(canon).get("mcpServers", {}) or {}
    out = []
    for name, cfg in sorted(data.items()):
        kind = "http" if cfg.get("url") or cfg.get("type") == "http" else "stdio"
        out.append({"name": name, "kind": kind, "url": cfg.get("url", "")})
    return out


# ---------------------------------------------------------------------------
# Mutations — reuse agent_control's tested CLI paths so the ledger + event
# stream fire exactly as they do from the terminal. Captures stdout for the id.
# ---------------------------------------------------------------------------


def control(argv: list[str]) -> dict:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = ac.main_inner(argv)
    except SystemExit as e:
        return {"ok": False, "error": str(e), "output": buf.getvalue().strip()}
    out = buf.getvalue().strip()
    return {"ok": code == 0, "code": code, "output": out}


def run_action(action: str, args: dict) -> dict:
    item_id = str(args.get("id", "")).strip()
    note = str(args.get("note", ""))
    if action == "approve":
        return control(["approve", "approve", item_id, "--note", note])
    if action == "reject":
        return control(["approve", "reject", item_id, "--note", note])
    if action == "queue_add":
        argv = [
            "queue",
            "add",
            "--repo",
            str(args.get("repo", "")),
            "--profile",
            str(args.get("profile", "")),
            "--agent",
            str(args.get("agent", "claude")),
            "--task",
            str(args.get("task", "")),
        ]
        return control(argv)
    if action == "queue_start":
        return control(["queue", "start"] + ([item_id] if item_id else []))
    if action == "queue_cancel":
        return control(["queue", "cancel", item_id])
    if action == "queue_retry":
        return control(["queue", "retry", item_id])
    # External ops: shelled, never imported.
    ext = {
        "sync": "mcp-sync && agents-sync",
        "doctor": "agents-doctor",
        "reboot": f"hcloud server reboot {shlex.quote(item_id)}" if item_id else None,
    }
    cmd = ext.get(action)
    if not cmd:
        raise HTTPException(status_code=400, detail=f"unknown action: {action}")
    code, out = sh(cmd, timeout=600)
    return {"ok": code == 0, "code": code, "output": out}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def require_token(request: Request) -> None:
    if not TOKEN:
        return
    sent = request.headers.get("x-agentd-token") or request.query_params.get("token")
    if sent != TOKEN:
        raise HTTPException(status_code=403, detail="bad token")


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("x-csrf-token")
    if not cookie or cookie != header or cookie != CSRF_TOKEN:
        raise HTTPException(status_code=403, detail="bad csrf")


# ---------------------------------------------------------------------------
# SSE — tail state/events.jsonl
# ---------------------------------------------------------------------------


async def event_stream(request: Request):
    path = ac.events_path()
    # Start at end of file: clients get a snapshot on connect, then only new events.
    pos = path.stat().st_size if path.exists() else 0
    snap = json.dumps({"type": "snapshot", **ac.query_snapshot()})
    yield f"event: snapshot\ndata: {snap}\n\n"
    while True:
        if await request.is_disconnected():
            break
        try:
            if path.exists():
                size = path.stat().st_size
                if size < pos:  # file trimmed/rotated
                    pos = 0
                if size > pos:
                    with path.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for line in chunk.splitlines():
                        line = line.strip()
                        if line:
                            yield f"event: ledger\ndata: {line}\n\n"
        except OSError:
            pass
        yield ": keepalive\n\n"
        await asyncio.sleep(1.5)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="agentd")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "agentd"}


@app.get("/api/snapshot")
def api_snapshot(request: Request) -> JSONResponse:
    require_token(request)
    return JSONResponse(ac.query_snapshot())


@app.get("/api/fleet")
def api_fleet(request: Request) -> JSONResponse:
    require_token(request)
    return JSONResponse(fleet())


@app.get("/api/profiles")
def api_profiles(request: Request) -> JSONResponse:
    require_token(request)
    return JSONResponse(ac.query_profiles())


@app.get("/api/ledger")
def api_ledger(request: Request, limit: int = 50) -> JSONResponse:
    require_token(request)
    return JSONResponse(ac.query_ledger(limit))


@app.get("/api/approvals")
def api_approvals(
    request: Request, status: str = "pending", limit: int = 50
) -> JSONResponse:
    require_token(request)
    return JSONResponse(ac.query_approvals(status, limit))


@app.get("/api/queue")
def api_queue(request: Request, status: str = "all", limit: int = 50) -> JSONResponse:
    require_token(request)
    return JSONResponse(ac.query_queue(status, limit))


@app.get("/api/evals")
def api_evals(request: Request) -> JSONResponse:
    require_token(request)
    return JSONResponse(ac.query_evals())


@app.get("/api/mcp")
def api_mcp(request: Request) -> JSONResponse:
    require_token(request)
    return JSONResponse(mcp_servers())


@app.get("/api/queue/{qid}/log")
def api_queue_log(request: Request, qid: str, lines: int = 200) -> JSONResponse:
    require_token(request)
    conn = ac.queue_db()
    row = ac.lookup_queue_task(conn, qid)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    log = Path(row["log"])
    text = ""
    if log.exists():
        text = "\n".join(
            log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        )
    return JSONResponse({"id": row["id"], "status": row["status"], "log": text})


@app.get("/events")
async def events(request: Request) -> StreamingResponse:
    require_token(request)
    return StreamingResponse(event_stream(request), media_type="text/event-stream")


@app.post("/api/action")
async def api_action(request: Request) -> JSONResponse:
    require_token(request)
    require_csrf(request)
    body = await request.json()
    action = body.get("action", "")
    args = body.get("args", {})
    return JSONResponse(run_action(action, args))


@app.get("/api/csrf")
def api_csrf(request: Request) -> JSONResponse:
    require_token(request)
    resp = JSONResponse({"csrf": CSRF_TOKEN})
    resp.set_cookie(
        CSRF_COOKIE, CSRF_TOKEN, httponly=True, samesite="strict", secure=False
    )
    return resp


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(
        "<h1>agentd</h1><p>Typed control-plane API. See <code>/healthz</code>, "
        "<code>/api/snapshot</code>, <code>/events</code>. The desktop app is the UI.</p>"
    )


def main() -> int:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
