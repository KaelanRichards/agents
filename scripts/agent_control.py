#!/usr/bin/env python3
"""Local control-plane helpers for profiles, runs, queue, approvals, and evals."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any


AH = Path(
    os.environ.get("AGENTS_HOME", str(Path.home() / ".config/agents"))
).expanduser()
STATE = Path(os.environ.get("AGENTS_STATE", str(AH / "state"))).expanduser()
PROFILES = AH / "profiles"
GENERATED = AH / "generated" / "profiles"
EVALS = AH / "evals" / "tasks"


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def ensure_state() -> None:
    STATE.mkdir(parents=True, exist_ok=True)


def events_path() -> Path:
    ensure_state()
    return STATE / "events.jsonl"


# Keep the live event log bounded so a long-running daemon tailing it never reads an
# unbounded file. We trim to the last N lines opportunistically on append.
EVENTS_MAX_LINES = 5000


def emit_event(event: dict[str, Any]) -> None:
    """Append a lightweight event to state/events.jsonl. This is the projection a daemon
    (agentd) tails to push live updates to clients — append-only and best-effort: an emit
    failure must never break the underlying control-plane action."""
    try:
        path = events_path()
        record = {"ts": event.get("ts") or now(), **event}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > EVENTS_MAX_LINES * 2:
                path.write_text(
                    "\n".join(lines[-EVENTS_MAX_LINES:]) + "\n", encoding="utf-8"
                )
        except OSError:
            pass
    except OSError:
        pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd)} timed out after {timeout}s"


def shell(cmd: str, cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return 124, (out + f"\ncommand timed out after {timeout}s").strip()


def expand_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def jj_revision(repo: Path) -> str:
    code, out = run(
        [
            "jj",
            "log",
            "-r",
            "@",
            "--no-graph",
            "-T",
            "change_id ++ ' ' ++ commit_id.short()",
        ],
        repo,
        15,
    )
    if code == 0 and out:
        return out.splitlines()[0].strip()
    code, out = run(["git", "rev-parse", "--short", "HEAD"], repo, 15)
    return out.strip() if code == 0 else ""


def profile_files() -> list[Path]:
    return sorted(PROFILES.glob("*.json"))


def load_profile(name: str) -> dict[str, Any]:
    path = PROFILES / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"unknown profile: {name}")
    data = load_json(path)
    validate_profile(data, path)
    return data


def validate_profile(data: dict[str, Any], path: Path) -> None:
    required = {
        "name": str,
        "description": str,
        "mcp_servers": list,
        "allowed_tools": list,
        "disallowed_tools": list,
        "filesystem": dict,
        "shell": dict,
        "confirm": list,
        "skills": list,
        "risk": str,
    }
    for key, typ in required.items():
        if key not in data or not isinstance(data[key], typ):
            raise SystemExit(f"{path}: {key} must be {typ.__name__}")
    if data["name"] != path.stem:
        raise SystemExit(f"{path}: name must match filename")
    if data["risk"] not in {"low", "medium", "high", "critical"}:
        raise SystemExit(f"{path}: risk must be low|medium|high|critical")


def cmd_profile(args: argparse.Namespace) -> int:
    if args.profile_cmd == "list":
        if getattr(args, "json", False):
            _print_json(query_profiles())
            return 0
        for path in profile_files():
            data = load_json(path)
            print(f"{data['name']}\t{data['risk']}\t{data['description']}")
        return 0
    if args.profile_cmd == "show":
        print(json.dumps(load_profile(args.name), indent=2, sort_keys=True))
        return 0
    if args.profile_cmd == "validate":
        for path in profile_files():
            validate_profile(load_json(path), path)
        print(f"profiles OK ({len(profile_files())})")
        return 0
    if args.profile_cmd == "compile":
        for path in profile_files():
            compile_profile(load_json(path))
        print(f"compiled {len(profile_files())} profile(s) into {GENERATED}")
        return 0
    if args.profile_cmd == "codex-flags":
        print(" ".join(codex_sandbox_args(load_profile(args.name))))
        return 0
    raise SystemExit("missing profile command")


def compile_profile(profile: dict[str, Any]) -> None:
    name = profile["name"]
    summary = textwrap.dedent(
        f"""\
        # Agent Profile: {name}

        {profile["description"]}

        Risk: {profile["risk"]}
        MCP servers: {", ".join(profile["mcp_servers"])}
        Allowed tools: {", ".join(profile["allowed_tools"])}
        Disallowed tools: {", ".join(profile["disallowed_tools"])}
        Confirm before: {", ".join(profile["confirm"])}
        Filesystem: {json.dumps(profile["filesystem"], sort_keys=True)}
        Shell: {json.dumps(profile["shell"], sort_keys=True)}
        Skills: {", ".join(profile["skills"])}
        """
    )
    (GENERATED / "claude").mkdir(parents=True, exist_ok=True)
    (GENERATED / "claude" / f"{name}.md").write_text(summary, encoding="utf-8")
    (GENERATED / "gemini" / name).mkdir(parents=True, exist_ok=True)
    (GENERATED / "gemini" / name / "GEMINI.md").write_text(summary, encoding="utf-8")
    (GENERATED / "qwen" / name).mkdir(parents=True, exist_ok=True)
    (GENERATED / "qwen" / name / "QWEN.md").write_text(summary, encoding="utf-8")
    write_json(GENERATED / "opencode" / f"{name}.json", profile)
    toml = [
        f'name = "{name}"',
        f'description = "{profile["description"]}"',
        f'risk = "{profile["risk"]}"',
        "mcp_servers = " + json.dumps(profile["mcp_servers"]),
        "allowed_tools = " + json.dumps(profile["allowed_tools"]),
        "disallowed_tools = " + json.dumps(profile["disallowed_tools"]),
        "confirm = " + json.dumps(profile["confirm"]),
        "skills = " + json.dumps(profile["skills"]),
        "",
    ]
    (GENERATED / "codex").mkdir(parents=True, exist_ok=True)
    (GENERATED / "codex" / f"{name}.toml").write_text("\n".join(toml), encoding="utf-8")
    compile_claude_settings(profile)


# Claude Code is the load-bearing target: a compiled profile becomes a real boundary via
# `agentp <profile>`, which launches Claude with `--strict-mcp-config` (only the profile's MCP
# servers are loaded) plus a `--settings` file whose permission deny/ask rules enforce the
# filesystem/shell mode and tool restrictions the profile declares. See bin/agentp.
EDIT_TOOLS = ["Edit", "MultiEdit", "NotebookEdit", "Write"]

# Concrete Claude permission rules for the few capabilities whose underlying MCP tool name is
# stable and known (the personal-actions facade). Other capabilities are enforced at the
# server level by the --strict-mcp-config subset rather than per-tool rules.
PERSONAL_CAPABILITY_TOOLS = {
    "gmail_send": "personal_gmail_send_email",
    "gmail_trash": "personal_gmail_trash_email",
    "slack_post": "personal_slack_send_message",
    "calendar_create": "personal_calendar_create_event",
    "calendar_update": "personal_calendar_update_event",
}

RISK_DEFAULT_MODE = {
    "low": "plan",
    "medium": "default",
    "high": "default",
    "critical": "default",
}


def claude_mcp_servers() -> dict[str, Any]:
    """Effective Claude MCP server map. Prefer the synced ~/.claude.json (placeholders already
    expanded + bearer→header mapped); fall back to canonical mcp.json so compile works on a fresh box."""
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        try:
            servers = load_json(claude_json).get("mcpServers")
            if isinstance(servers, dict):
                return servers
        except (json.JSONDecodeError, OSError):
            pass
    canon = AH / "mcp.json"
    if canon.exists():
        return load_json(canon).get("mcpServers", {}) or {}
    return {}


def compile_claude_settings(profile: dict[str, Any]) -> None:
    name = profile["name"]
    servers = claude_mcp_servers()
    allow_servers = set(profile["mcp_servers"])
    deny: list[str] = []
    ask: list[str] = []
    # Server isolation (defense-in-depth alongside --strict-mcp-config): deny every known MCP
    # server the profile does not grant.
    for srv in sorted(set(servers) - allow_servers):
        deny.append(f"mcp__{srv}")
    # Filesystem mode → block file mutations for read-only/none profiles.
    if (profile.get("filesystem") or {}).get("mode") in {"read-only", "none"}:
        deny.extend(EDIT_TOOLS)
    # Shell mode → none blocks Bash outright; ask/confirm-each route it through a prompt.
    shell_mode = (profile.get("shell") or {}).get("mode")
    if shell_mode == "none":
        deny.append("Bash")
    elif shell_mode in {"ask", "confirm-each"}:
        ask.append("Bash")
    # Per-tool rules for the known personal-actions capabilities.
    for cap in profile.get("disallowed_tools", []):
        tool = PERSONAL_CAPABILITY_TOOLS.get(cap)
        if tool:
            deny.append(f"mcp__personal-actions__{tool}")
    for cap in profile.get("confirm", []):
        tool = PERSONAL_CAPABILITY_TOOLS.get(cap)
        if tool:
            ask.append(f"mcp__personal-actions__{tool}")
    settings = {
        "$comment": f"compiled from profiles/{name}.json by `agent-profile compile` — do not edit by hand",
        "permissions": {
            "defaultMode": RISK_DEFAULT_MODE.get(profile["risk"], "default"),
            "allow": [],
            "deny": sorted(set(deny)),
            "ask": sorted(set(ask)),
        },
        "sandbox": compile_sandbox(profile),
    }
    (GENERATED / "claude").mkdir(parents=True, exist_ok=True)
    write_json(GENERATED / "claude" / f"{name}.settings.json", settings)
    subset = {srv: servers[srv] for srv in profile["mcp_servers"] if srv in servers}
    write_json(GENERATED / "claude" / f"{name}.mcp.json", {"mcpServers": subset})


# Credential dirs the OS sandbox should hide from Bash subprocesses. Claude's default read
# policy still exposes ~/.ssh and ~/.aws, so denying them is a real hardening win, not cosmetic.
SANDBOX_DENY_READ = ["~/.ssh", "~/.aws", "~/.config/gcloud", "~/.config/agents-secrets"]
# Tools that are known-incompatible with the OS sandbox; they fall back to the normal permission
# flow rather than failing the task (docker/gcloud/gh/terraform per Claude's sandbox docs).
SANDBOX_EXCLUDED = [
    "docker *",
    "gcloud *",
    "gh *",
    "terraform *",
    "kubectl *",
    "jest *",
]


def compile_sandbox(profile: dict[str, Any]) -> dict[str, Any]:
    """Native OS-level Bash sandbox (Seatbelt/bubblewrap) for the profile. Complements the
    Edit/Write deny rules above (which the sandbox does NOT cover — it is Bash-only) by confining
    what Bash subprocesses can write and read. Degrades to a warning if deps are missing."""
    fs = profile.get("filesystem") or {}
    allow_write = ["/tmp"]
    # Only a workspace-write profile grants extra writable roots to Bash. read-only/none profiles
    # get no extra write scope — `roots` there is READ scope, not write scope. (The working dir is
    # always sandbox-writable, but Bash is ask/deny-gated for those profiles anyway.)
    if fs.get("mode") == "workspace-write":
        for root in fs.get("roots") or []:
            # current_repo == the working dir, which the sandbox already grants by default.
            if root and root != "current_repo":
                allow_write.append(root)
    return {
        "enabled": True,
        "filesystem": {
            "allowWrite": sorted(set(allow_write)),
            "denyRead": SANDBOX_DENY_READ,
        },
        "excludedCommands": SANDBOX_EXCLUDED,
    }


def codex_sandbox_args(profile: dict[str, Any]) -> list[str]:
    """Native Codex containment for a profile: --sandbox + --ask-for-approval. Codex's sandbox is
    OS-enforced like Claude's; approval policy tightens with risk. (Codex has no --strict-mcp-config
    equivalent, so server subsetting is not enforced there — containment is via sandbox+approval.)"""
    fs_mode = (profile.get("filesystem") or {}).get("mode")
    sandbox = "workspace-write" if fs_mode == "workspace-write" else "read-only"
    approval = (
        "untrusted" if profile.get("risk") in {"high", "critical"} else "on-request"
    )
    return ["--sandbox", sandbox, "--ask-for-approval", approval]


def ledger_path() -> Path:
    ensure_state()
    path = STATE / "runs" / f"{today()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def chain_head_path() -> Path:
    ensure_state()
    return STATE / "runs" / ".chain-head"


def ledger_hash(entry: dict[str, Any]) -> str:
    """SHA-256 over the canonical entry (excluding the hash field itself). Because each entry
    embeds `prev` (the previous entry's hash), the hashes form a tamper-evident chain."""
    material = json.dumps(
        {k: v for k, v in entry.items() if k != "hash"},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append_ledger(entry: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "id": entry.get("id") or str(uuid.uuid4()),
        "ts": entry.get("ts") or now(),
        **entry,
    }
    # Serialize the read-prev → append → write-head critical section across processes (the
    # detached queue worker and a foreground command can both append), so two entries can't
    # capture the same prev and clobber the head — which would show up as a false chain break.
    head = chain_head_path()
    runs_dir = STATE / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runs_dir / ".chain.lock"
    with open(lock_path, "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entry["prev"] = (
            head.read_text(encoding="utf-8").strip() if head.exists() else ""
        )
        entry["hash"] = ledger_hash(entry)
        with ledger_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        head.write_text(entry["hash"] + "\n", encoding="utf-8")
    # Every ledger append is a control-plane transition (queue/approval/broker/eval/taint),
    # so projecting it onto the event stream gives clients one live feed for all of them.
    emit_event(
        {
            "ts": entry["ts"],
            "type": "ledger",
            "kind": entry.get("kind", ""),
            "status": entry.get("status", ""),
            "id": entry.get("id", ""),
            "profile": entry.get("profile", ""),
            "agent": entry.get("agent", ""),
            "repo": entry.get("repo", ""),
            "summary": entry.get("prompt", ""),
            "details": entry.get("details", {}),
        }
    )
    return entry


def verify_ledger() -> dict[str, Any]:
    """Walk the ledger in chronological order and verify the hash chain. Entries that predate
    the chain (no `hash` field) are counted as legacy and skipped, so a mixed ledger verifies
    cleanly from the first hashed entry onward."""
    entries = iter_ledger()
    prev = ""
    checked = 0
    legacy = 0
    for index, entry in enumerate(entries):
        if "hash" not in entry:
            legacy += 1
            continue
        if ledger_hash(entry) != entry["hash"]:
            return {
                "ok": False,
                "reason": "hash mismatch",
                "index": index,
                "id": entry.get("id"),
                "checked": checked,
                "legacy": legacy,
            }
        if entry.get("prev", "") != prev:
            return {
                "ok": False,
                "reason": "broken chain link",
                "index": index,
                "id": entry.get("id"),
                "checked": checked,
                "legacy": legacy,
            }
        prev = entry["hash"]
        checked += 1
    return {"ok": True, "checked": checked, "legacy": legacy, "total": len(entries)}


def iter_ledger() -> list[dict[str, Any]]:
    base = STATE / "runs"
    if not base.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


def cmd_ledger(args: argparse.Namespace) -> int:
    if args.ledger_cmd == "record":
        repo = expand_path(args.repo) if args.repo else Path.cwd()
        entry = append_ledger(
            {
                "kind": args.kind,
                "status": args.status,
                "profile": args.profile,
                "agent": args.agent,
                "repo": str(repo),
                "revision": jj_revision(repo) if repo.exists() else "",
                "prompt": args.prompt,
                "details": json.loads(args.details or "{}"),
            }
        )
        print(json.dumps(entry, indent=2, sort_keys=True))
        return 0
    if args.ledger_cmd == "list":
        entries = query_ledger(args.limit)
        if getattr(args, "json", False):
            _print_json(entries)
            return 0
        for e in entries:
            print(
                f"{e.get('ts', '')}\t{e.get('id', '')}\t{e.get('kind', '')}\t{e.get('status', '')}\t{e.get('profile', '')}\t{e.get('repo', '')}"
            )
        return 0
    if args.ledger_cmd == "show":
        for e in iter_ledger():
            if e.get("id") == args.id:
                print(json.dumps(e, indent=2, sort_keys=True))
                return 0
        raise SystemExit(f"run not found: {args.id}")
    if args.ledger_cmd == "verify":
        result = verify_ledger()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    raise SystemExit("missing ledger command")


def db(name: str) -> sqlite3.Connection:
    ensure_state()
    conn = sqlite3.connect(STATE / name)
    conn.row_factory = sqlite3.Row
    return conn


def approval_db() -> sqlite3.Connection:
    conn = db("approvals.sqlite")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          kind TEXT NOT NULL,
          summary TEXT NOT NULL,
          payload TEXT NOT NULL,
          status TEXT NOT NULL,
          decision_note TEXT NOT NULL DEFAULT ''
        )
        """
    )
    migrate_approval_db(conn)
    return conn


def migrate_approval_db(conn: sqlite3.Connection) -> None:
    if "expires_at" not in table_columns(conn, "approvals"):
        conn.execute(
            "ALTER TABLE approvals ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''"
        )


DEFAULT_APPROVAL_TTL_HOURS = 24.0


def approval_expiry(ttl_hours: float) -> str:
    if ttl_hours <= 0:
        return ""
    return (dt.datetime.now(dt.UTC) + dt.timedelta(hours=ttl_hours)).isoformat()


def expire_approvals(conn: sqlite3.Connection) -> int:
    """Auto-reject pending approvals whose TTL has elapsed so the inbox cannot accumulate
    forever-pending items (and a stale request can never be silently honored later)."""
    ts = now()
    rows = conn.execute(
        "SELECT id, expires_at FROM approvals WHERE status = 'pending' AND expires_at != '' AND expires_at < ?",
        (ts,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE approvals SET status = 'expired', updated_at = ?, decision_note = ? WHERE id = ?",
            (ts, "auto-expired: TTL elapsed before approval", row["id"]),
        )
        append_ledger(
            {
                "kind": "approval",
                "status": "expired",
                "profile": "",
                "agent": "",
                "repo": "",
                "prompt": row["id"],
                "details": {"expires_at": row["expires_at"]},
            }
        )
    if rows:
        conn.commit()
    return len(rows)


def cmd_approve(args: argparse.Namespace) -> int:
    conn = approval_db()
    expired = expire_approvals(conn)
    if args.approve_cmd == "expire":
        print(expired)
        return 0
    if args.approve_cmd == "request":
        aid = str(uuid.uuid4())
        payload = args.payload or "{}"
        json.loads(payload)
        expires_at = approval_expiry(args.ttl_hours)
        conn.execute(
            "INSERT INTO approvals (id, created_at, updated_at, kind, summary, payload, status, decision_note, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?)",
            (aid, now(), now(), args.kind, args.summary, payload, expires_at),
        )
        conn.commit()
        append_ledger(
            {
                "kind": "approval",
                "status": "pending",
                "profile": "",
                "agent": "",
                "repo": "",
                "prompt": args.summary,
                "details": {
                    "approval_id": aid,
                    "approval_kind": args.kind,
                    "expires_at": expires_at,
                },
            }
        )
        print(aid)
        return 0
    if args.approve_cmd == "list":
        rows = conn.execute(
            "SELECT * FROM approvals WHERE (? = 'all' OR status = ?) ORDER BY created_at DESC LIMIT ?",
            (args.status, args.status, args.limit),
        ).fetchall()
        if getattr(args, "json", False):
            _print_json([dict(r) for r in rows])
            return 0
        for r in rows:
            print(
                f"{r['created_at']}\t{r['id']}\t{r['status']}\t{r['kind']}\t{r['summary']}"
            )
        return 0
    if args.approve_cmd == "show":
        row = lookup_approval(conn, args.id)
        if not row:
            raise SystemExit(f"approval not found: {args.id}")
        print(json.dumps(dict(row), indent=2, sort_keys=True))
        return 0
    if args.approve_cmd in {"approve", "reject"}:
        status = "approved" if args.approve_cmd == "approve" else "rejected"
        row = lookup_approval(conn, args.id)
        if not row:
            raise SystemExit(f"approval not found: {args.id}")
        conn.execute(
            "UPDATE approvals SET status = ?, updated_at = ?, decision_note = ? WHERE id = ?",
            (status, now(), args.note or "", row["id"]),
        )
        conn.commit()
        append_ledger(
            {
                "kind": "approval",
                "status": status,
                "profile": "",
                "agent": "",
                "repo": "",
                "prompt": row["id"],
                "details": {"note": args.note or ""},
            }
        )
        print(status)
        return 0
    raise SystemExit("missing approval command")


def lookup_approval(conn: sqlite3.Connection, approval_id: str) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM approvals WHERE id = ?", (approval_id,)
    ).fetchone()
    if row:
        return row
    rows = conn.execute(
        "SELECT * FROM approvals WHERE id LIKE ?", (approval_id + "%",)
    ).fetchall()
    if len(rows) > 1:
        raise SystemExit(f"approval id prefix is ambiguous: {approval_id}")
    return rows[0] if rows else None


def queue_db() -> sqlite3.Connection:
    conn = db("agentq.sqlite")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          status TEXT NOT NULL,
          repo TEXT NOT NULL,
          workspace TEXT NOT NULL,
          profile TEXT NOT NULL,
          agent TEXT NOT NULL,
          task TEXT NOT NULL,
          session TEXT NOT NULL,
          log TEXT NOT NULL
        )
        """
    )
    migrate_queue_db(conn)
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def migrate_queue_db(conn: sqlite3.Connection) -> None:
    cols = table_columns(conn, "tasks")
    additions = {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "max_attempts": "INTEGER NOT NULL DEFAULT 1",
        "timeout_seconds": "INTEGER NOT NULL DEFAULT 3600",
        "exit_code": "INTEGER",
        "completed_at": "TEXT NOT NULL DEFAULT ''",
        "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, ddl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {ddl}")


def workspace_for(repo: Path, qid: str) -> Path:
    return repo.parent / f"{repo.name}-workspaces" / f"agentq-{qid[:8]}"


def cmd_queue(args: argparse.Namespace) -> int:
    conn = queue_db()
    if args.queue_cmd == "add":
        repo = expand_path(args.repo)
        load_profile(args.profile)
        qid = str(uuid.uuid4())
        ws = workspace_for(repo, qid)
        log = STATE / "agentq-logs" / f"{qid}.log"
        session = f"agentq-{qid[:8]}"
        conn.execute(
            """
            INSERT INTO tasks (
              id, created_at, updated_at, status, repo, workspace, profile, agent, task, session, log,
              attempts, max_attempts, timeout_seconds, exit_code, completed_at, cancel_requested
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, '', 0)
            """,
            (
                qid,
                now(),
                now(),
                str(repo),
                str(ws),
                args.profile,
                args.agent,
                args.task,
                session,
                str(log),
                args.max_attempts,
                args.timeout,
            ),
        )
        conn.commit()
        append_ledger(
            {
                "kind": "queue",
                "status": "queued",
                "profile": args.profile,
                "agent": args.agent,
                "repo": str(repo),
                "prompt": args.task,
                "details": {"queue_id": qid, "workspace": str(ws)},
            }
        )
        print(qid)
        return 0
    if args.queue_cmd == "list":
        rows = conn.execute(
            "SELECT * FROM tasks WHERE (? = 'all' OR status = ?) ORDER BY created_at DESC LIMIT ?",
            (args.status, args.status, args.limit),
        ).fetchall()
        if getattr(args, "json", False):
            _print_json([dict(r) for r in rows])
            return 0
        for r in rows:
            print(
                f"{r['created_at']}\t{r['id']}\t{r['status']}\t{r['profile']}\t{r['agent']}\t{r['repo']}\t{r['task'][:80]}"
            )
        return 0
    if args.queue_cmd == "show":
        row = lookup_queue_task(conn, args.id)
        if not row:
            raise SystemExit(f"task not found: {args.id}")
        print(json.dumps(dict(row), indent=2, sort_keys=True))
        return 0
    if args.queue_cmd == "start":
        row = select_queue_task(conn, args.id)
        if not row:
            raise SystemExit("no queued task found")
        start_queue_task(conn, row, foreground=args.foreground)
        return 0
    if args.queue_cmd == "run":
        row = lookup_queue_task(conn, args.id)
        if not row:
            raise SystemExit(f"task not found: {args.id}")
        run_queue_task(conn, row)
        return 0
    if args.queue_cmd == "finish":
        finish_queue_task(conn, args.id, args.exit_code, args.status)
        return 0
    if args.queue_cmd == "cancel":
        cancel_queue_task(conn, args.id)
        return 0
    if args.queue_cmd == "retry":
        retry_queue_task(conn, args.id)
        return 0
    if args.queue_cmd == "tail":
        tail_queue_task(conn, args.id, args.lines, args.follow)
        return 0
    if args.queue_cmd == "reconcile":
        reconcile_queue(conn)
        return 0
    if args.queue_cmd == "worker":
        reconcile_queue(conn)
        row = select_queue_task(conn, "")
        if not row:
            print("agentq: no queued task")
            return 0
        start_queue_task(conn, row, foreground=False)
        return 0
    raise SystemExit("missing queue command")


def select_queue_task(conn: sqlite3.Connection, qid: str) -> sqlite3.Row | None:
    if qid:
        return lookup_queue_task(conn, qid)
    return conn.execute(
        "SELECT * FROM tasks WHERE status = 'queued' ORDER BY created_at LIMIT 1"
    ).fetchone()


def lookup_queue_task(conn: sqlite3.Connection, qid: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (qid,)).fetchone()
    if row:
        return row
    rows = conn.execute("SELECT * FROM tasks WHERE id LIKE ?", (qid + "%",)).fetchall()
    if len(rows) > 1:
        raise SystemExit(f"task id prefix is ambiguous: {qid}")
    return rows[0] if rows else None


def start_queue_task(
    conn: sqlite3.Connection, row: sqlite3.Row, foreground: bool
) -> None:
    if row["status"] not in {"queued", "failed", "canceled"}:
        raise SystemExit(f"task {row['id']} is {row['status']}, not queued")
    if int(row["attempts"]) >= int(row["max_attempts"]):
        raise SystemExit(
            f"task {row['id']} has exhausted attempts ({row['attempts']}/{row['max_attempts']})"
        )
    repo = Path(row["repo"])
    ws = Path(row["workspace"])
    log = Path(row["log"])
    log.parent.mkdir(parents=True, exist_ok=True)
    if not ws.exists():
        ws.parent.mkdir(parents=True, exist_ok=True)
        code, out = run(
            ["jj", "-R", str(repo), "workspace", "add", str(ws)], timeout=120
        )
        if code != 0:
            conn.execute(
                "UPDATE tasks SET status = 'failed', updated_at = ? WHERE id = ?",
                (now(), row["id"]),
            )
            conn.commit()
            raise SystemExit(out)
    conn.execute(
        "UPDATE tasks SET status = 'running', updated_at = ?, attempts = attempts + 1, cancel_requested = 0 WHERE id = ?",
        (now(), row["id"]),
    )
    conn.commit()
    append_ledger(
        {
            "kind": "queue",
            "status": "running",
            "profile": row["profile"],
            "agent": row["agent"],
            "repo": row["repo"],
            "prompt": row["task"],
            "details": {
                "queue_id": row["id"],
                "workspace": str(ws),
                "session": row["session"],
            },
        }
    )
    if row["agent"] == "noop" or foreground:
        updated = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (row["id"],)
        ).fetchone()
        assert updated
        run_queue_task(conn, updated)
        return
    runner = AH / "scripts" / "agent_control.py"
    tmux_cmd = f"python3 {shlex.quote(str(runner))} queue run {shlex.quote(row['id'])}"
    code, out = run(
        ["tmux", "new-session", "-d", "-s", row["session"], tmux_cmd], timeout=30
    )
    if code != 0:
        raise SystemExit(out)
    print(f"started {row['id']} session={row['session']} log={log}")


def run_queue_task(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    ws = Path(row["workspace"])
    log = Path(row["log"])
    command = agent_command(row["agent"], row["task"], row["profile"])
    timeout = int(row["timeout_seconds"])
    code, out = shell(command, ws, timeout=timeout)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(out + "\n", encoding="utf-8")
    cancel_row = conn.execute(
        "SELECT cancel_requested FROM tasks WHERE id = ?", (row["id"],)
    ).fetchone()
    status = (
        "canceled"
        if cancel_row and int(cancel_row["cancel_requested"])
        else ("done" if code == 0 else "failed")
    )
    finish_queue_task(conn, row["id"], code, status)
    print(f"{status}: {row['id']} log={log}")


def finish_queue_task(
    conn: sqlite3.Connection, qid: str, exit_code: int, status: str = ""
) -> None:
    if not status:
        status = "done" if int(exit_code) == 0 else "failed"
    row = lookup_queue_task(conn, qid)
    if not row:
        raise SystemExit(f"task not found: {qid}")
    conn.execute(
        "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ?, exit_code = ? WHERE id = ?",
        (status, now(), now(), int(exit_code), row["id"]),
    )
    conn.commit()
    append_ledger(
        {
            "kind": "queue",
            "status": status,
            "profile": row["profile"],
            "agent": row["agent"],
            "repo": row["repo"],
            "prompt": row["task"],
            "details": {
                "queue_id": row["id"],
                "exit_code": int(exit_code),
                "log": row["log"],
            },
        }
    )


def cancel_queue_task(conn: sqlite3.Connection, qid: str) -> None:
    row = lookup_queue_task(conn, qid)
    if not row:
        raise SystemExit(f"task not found: {qid}")
    if row["status"] == "running":
        run(["tmux", "kill-session", "-t", row["session"]], timeout=15)
    conn.execute(
        "UPDATE tasks SET status = 'canceled', updated_at = ?, completed_at = ?, cancel_requested = 1 WHERE id = ?",
        (now(), now(), row["id"]),
    )
    conn.commit()
    append_ledger(
        {
            "kind": "queue",
            "status": "canceled",
            "profile": row["profile"],
            "agent": row["agent"],
            "repo": row["repo"],
            "prompt": row["task"],
            "details": {"queue_id": row["id"]},
        }
    )
    print(f"canceled: {row['id']}")


def retry_queue_task(conn: sqlite3.Connection, qid: str) -> None:
    row = lookup_queue_task(conn, qid)
    if not row:
        raise SystemExit(f"task not found: {qid}")
    if row["status"] not in {"failed", "canceled"}:
        raise SystemExit(
            f"task {qid} is {row['status']}; only failed/canceled tasks can be retried"
        )
    conn.execute(
        "UPDATE tasks SET status = 'queued', updated_at = ?, completed_at = '', exit_code = NULL, cancel_requested = 0 WHERE id = ?",
        (now(), row["id"]),
    )
    conn.commit()
    append_ledger(
        {
            "kind": "queue",
            "status": "retried",
            "profile": row["profile"],
            "agent": row["agent"],
            "repo": row["repo"],
            "prompt": row["task"],
            "details": {"queue_id": row["id"]},
        }
    )
    print(f"queued: {row['id']}")


def tail_queue_task(
    conn: sqlite3.Connection, qid: str, lines: int, follow: bool
) -> None:
    row = lookup_queue_task(conn, qid)
    if not row:
        raise SystemExit(f"task not found: {qid}")
    log = Path(row["log"])
    if not log.exists():
        print("(no log yet)")
        return
    printed = 0
    while True:
        content = log.read_text(encoding="utf-8", errors="replace").splitlines()
        chunk = content[-lines:]
        if len(chunk) != printed:
            print("\n".join(chunk))
            printed = len(chunk)
        if not follow:
            return
        current = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (qid,)
        ).fetchone()
        if current and current["status"] not in {"running", "queued"}:
            return
        time.sleep(2)


def reconcile_queue(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM tasks WHERE status = 'running'").fetchall()
    for row in rows:
        code, _ = run(["tmux", "has-session", "-t", row["session"]], timeout=10)
        if code == 0:
            continue
        log = Path(row["log"])
        status = "failed"
        exit_code = 1
        if (
            log.exists()
            and "Traceback"
            not in log.read_text(encoding="utf-8", errors="replace")[-4000:]
        ):
            status = "done" if row["agent"] == "noop" else "failed"
        finish_queue_task(conn, row["id"], exit_code, status)
        print(f"reconciled {row['id']} -> {status}")


def agent_command(agent: str, task: str, profile: str = "") -> str:
    """Build the shell command to run `agent` on `task`. When a profile is given, Claude is
    launched UNDER that profile's compiled boundary (same artifacts agentp uses): the granted MCP
    subset via --strict-mcp-config, the deny/ask settings, and AGENTS_PROFILE exported so the
    profile-broker PreToolUse hook enforces per-tool read/write policy. Without this, a queued run
    would ignore its profile and run unconstrained."""
    quoted = shlex.quote(task)
    if agent == "noop":
        return f"printf '%s\\n' {quoted}"
    if agent == "claude":
        if profile:
            settings = GENERATED / "claude" / f"{profile}.settings.json"
            mcpcfg = GENERATED / "claude" / f"{profile}.mcp.json"
            if settings.exists() and mcpcfg.exists():
                return (
                    f"AGENTS_PROFILE={shlex.quote(profile)} claude "
                    f"--settings {shlex.quote(str(settings))} "
                    f"--mcp-config {shlex.quote(str(mcpcfg))} --strict-mcp-config "
                    f"-p --permission-mode auto {quoted}"
                )
        return f"claude -p --permission-mode auto {quoted}"
    if agent == "codex":
        # Codex headless: native sandbox flags from the profile (no --strict-mcp-config in codex).
        if profile:
            flags = " ".join(codex_sandbox_args(load_profile(profile)))
            return f"codex exec {flags} {quoted}"
        return f"codex exec --full-auto {quoted}"
    if agent == "opencode":
        return f"opencode run {quoted}"
    if agent == "gemini":
        return f"gemini -p {quoted}"
    if agent == "qwen":
        return f"qwen -p {quoted}"
    raise SystemExit(f"unsupported agent: {agent}")


MUTATING_TOOL_WORDS = {
    "add",
    "approve",
    "archive",
    "assign",
    "cancel",
    "close",
    "create",
    "delete",
    "deploy",
    "edit",
    "execute",
    "ignore",
    "merge",
    "mute",
    "post",
    "provision",
    "push",
    "reboot",
    "reject",
    "release",
    "remove",
    "resolve",
    "restore",
    "run",
    "send",
    "start",
    "sync",
    "teardown",
    "trash",
    "update",
    "write",
}

CAPABILITY_TOOLS = {
    "personal_search": {
        "personal_slack_search_messages",
        "personal_gmail_search_messages",
        "personal_gmail_get_message",
        "personal_drive_search_files",
    },
    "personal_gmail_draft": {"personal_gmail_create_draft"},
    "personal_calendar_list": {"personal_calendar_list_events"},
    "gmail_send": {"personal_gmail_send_email"},
    "gmail_trash": {"personal_gmail_trash_email"},
    "slack_post": {"personal_slack_send_message"},
    "calendar_create": {"personal_calendar_create_event"},
    "calendar_update": {"personal_calendar_update_event"},
    "bigquery_readonly": {"bigquery_execute_sql_readonly", "bigquery_dry_run_sql"},
    "repo_status": {"repo_status"},
    "repo_log": {"repo_log"},
    "repo_diff": {"repo_diff"},
    "list_tasks": {"list_tasks"},
    "run_tests": {"run_task"},
    "gh_read": {"gh_read"},
    "gh_pr_create": {"gh_pr_create"},
    "github_read": {"github_read"},
    "linear_read": {"linear_read"},
    "datadog_write": {"datadog_write"},
    "sentry_write": {"sentry_write"},
    "bigquery_write": {"bigquery_write"},
}

READ_CAPABILITY_SERVERS = {
    "datadog_read": "datadog",
    "sentry_read": "sentry",
    "github_read": "github",
    "linear_read": "linear",
    "notion_read": "notion",
    "granola_read": "granola",
}


# Authoritative per-tool effect classification. This is the source of truth the broker uses
# instead of guessing from the tool *name* — which is trivially evaded by a synonym (the
# `personalize_email` vs `send_email` problem). Any tool not listed here is classified by the
# fallback in `classify_effect`, which fails CLOSED (treats unknown tools on write-capable
# servers as mutations) so a newly-added tool can never silently bypass confirmation.
TOOL_EFFECTS = {
    # personal-actions facade
    "personal_slack_send_message": "write",
    "personal_gmail_send_email": "write",
    "personal_gmail_create_draft": "write",
    "personal_gmail_trash_email": "destructive",
    "personal_calendar_create_event": "write",
    "personal_calendar_update_event": "write",
    "personal_slack_search_messages": "read",
    "personal_gmail_search_messages": "read",
    "personal_gmail_get_message": "read",
    "personal_calendar_list_events": "read",
    "personal_drive_search_files": "read",
    # agents MCP
    "repo_status": "read",
    "repo_log": "read",
    "repo_diff": "read",
    "list_tasks": "read",
    "list_mcp_servers": "read",
    "list_agent_profiles": "read",
    "list_agent_runs": "read",
    "get_agent_run": "read",
    "list_agent_queue": "read",
    "list_pending_approvals": "read",
    "run_task": "write",
    "sync_config": "write",
    # bigquery facade (read-only by construction)
    "bigquery_execute_sql_readonly": "read",
    "bigquery_dry_run_sql": "read",
    # agent-broker (policy queries only)
    "list_profiles": "read",
    "get_profile": "read",
    "authorize_tool_call": "read",
}

WRITE_EFFECTS = {"write", "destructive"}

# Servers that have no mutating surface at all — unknown tools here stay read-classified.
READ_ONLY_SERVERS = {"context7", "sequential-thinking", "bigquery"}

# Read-intent verbs: an unknown tool whose name contains one of these is treated as a read
# even on a write-capable server (most genuine read tools are search/get/list/...).
READ_INTENT_WORDS = {
    "read",
    "get",
    "list",
    "search",
    "show",
    "describe",
    "status",
    "log",
    "logs",
    "diff",
    "dry",
    "fetch",
    "find",
    "query",
    "view",
    "aggregate",
    "analyze",
    "trace",
    "whoami",
    "summary",
    "details",
    "context",
}


def tool_words(tool: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", tool.lower()) if part}


def classify_effect(server: str, tool: str, caller_marked_mutation: bool) -> str:
    """Return 'read', 'write', or 'destructive' for a (server, tool). Authoritative registry
    first; then a fail-closed fallback so unknown tools on write-capable servers count as
    mutations rather than slipping through as reads."""
    tool_key = tool.lower()
    words = tool_words(tool)
    if tool_key in TOOL_EFFECTS:
        effect = TOOL_EFFECTS[tool_key]
    elif server in READ_ONLY_SERVERS:
        effect = "read"
    elif words & MUTATING_TOOL_WORDS:
        effect = "write"
    elif words & READ_INTENT_WORDS:
        effect = "read"
    else:
        effect = "write"  # fail closed: unknown, no read signal, write-capable server
    if caller_marked_mutation and effect == "read":
        effect = "write"
    return effect


def infer_mutation(tool: str, mutation: bool, server: str = "") -> bool:
    return classify_effect(server, tool, mutation) in WRITE_EFFECTS


def capability_matches(
    capability: str, server: str, tool: str, inferred_mutation: bool
) -> bool:
    tool_key = tool.lower()
    if tool_key in CAPABILITY_TOOLS.get(capability, set()):
        return True
    if capability in READ_CAPABILITY_SERVERS:
        expected_server = READ_CAPABILITY_SERVERS[capability]
        return server == expected_server and not inferred_mutation
    if capability == "read":
        return not inferred_mutation
    if capability == "confirmed_mutation":
        return inferred_mutation
    return tool_key == capability or tool_key.startswith(f"{capability}_")


def capability_list_matches(
    capabilities: list[str], server: str, tool: str, inferred_mutation: bool
) -> bool:
    return any(
        capability_matches(capability, server, tool, inferred_mutation)
        for capability in capabilities
    )


def cmd_eval(args: argparse.Namespace) -> int:
    if args.eval_cmd == "list":
        if getattr(args, "json", False):
            _print_json(query_evals())
            return 0
        for path in sorted(EVALS.glob("*.json")):
            data = load_json(path)
            print(
                f"{data['id']}\t{data.get('profile', '')}\t{data.get('description', '')}"
            )
        return 0
    if args.eval_cmd == "run":
        task_path = EVALS / f"{args.id}.json"
        if not task_path.exists():
            raise SystemExit(f"eval not found: {args.id}")
        task = load_json(task_path)
        repo = expand_path(task.get("repo", "~/.config/agents"))
        profile = args.profile or task.get("profile", "plan-readonly")
        agent = args.agent or task.get("agent", "noop")
        load_profile(profile)
        append_ledger(
            {
                "kind": "eval",
                "status": "started",
                "profile": profile,
                "agent": agent,
                "repo": str(repo),
                "prompt": task["prompt"],
                "details": {"eval_id": task["id"]},
            }
        )
        if agent != "noop":
            qid_code = main_inner(
                [
                    "queue",
                    "add",
                    "--repo",
                    str(repo),
                    "--profile",
                    profile,
                    "--agent",
                    agent,
                    "--task",
                    task["prompt"],
                ]
            )
            return qid_code
        code, out = shell(
            task.get("success_command", "true"), repo, timeout=args.timeout
        )
        status = "passed" if code == 0 else "failed"
        append_ledger(
            {
                "kind": "eval",
                "status": status,
                "profile": profile,
                "agent": agent,
                "repo": str(repo),
                "prompt": task["prompt"],
                "details": {
                    "eval_id": task["id"],
                    "exit_code": code,
                    "output": out[-4000:],
                },
            }
        )
        print(out)
        print(f"eval {task['id']}: {status}")
        return code
    raise SystemExit("missing eval command")


def broker_authorize(
    profile_name: str,
    server: str,
    tool: str,
    mutation: bool,
    context_tainted: bool = False,
) -> dict[str, Any]:
    profile = load_profile(profile_name)
    allowed_server = server in profile["mcp_servers"]
    effect = classify_effect(server, tool, mutation)
    inferred_mutation = effect in WRITE_EFFECTS
    disallowed = capability_list_matches(
        profile["disallowed_tools"], server, tool, inferred_mutation
    )
    allowed_tool = capability_list_matches(
        profile["allowed_tools"], server, tool, inferred_mutation
    )
    confirm_tool = capability_list_matches(
        profile["confirm"], server, tool, inferred_mutation
    )
    if confirm_tool:
        allowed_tool = True
    needs_confirm = inferred_mutation or confirm_tool
    allowed = allowed_server and allowed_tool and not disallowed
    reason = "ok" if allowed else "server/tool denied by profile"
    if inferred_mutation and profile["risk"] in {"high", "critical"}:
        needs_confirm = True
    # Provenance rule (CaMeL-style): data drawn from an untrusted/tainted context must never
    # silently authorize a mutation. Any write triggered under taint requires confirmation; on
    # high/critical profiles it is refused outright so injected content cannot drive a write.
    if context_tainted and inferred_mutation:
        needs_confirm = True
        if profile["risk"] in {"high", "critical"}:
            allowed = False
            reason = "write blocked: mutation triggered in untrusted (tainted) context"
    return {
        "allowed": allowed,
        "needs_confirmation": needs_confirm,
        "profile": profile_name,
        "server": server,
        "tool": tool,
        "effect": effect,
        "mutation": inferred_mutation,
        "caller_marked_mutation": mutation,
        "context_tainted": bool(context_tainted),
        "reason": reason,
    }


def cmd_broker(args: argparse.Namespace) -> int:
    decision = broker_authorize(
        args.profile, args.server, args.tool, args.mutation, args.context_tainted
    )
    append_ledger(
        {
            "kind": "broker",
            "status": "allowed" if decision["allowed"] else "denied",
            "profile": args.profile,
            "agent": "",
            "repo": "",
            "prompt": f"{args.server}.{args.tool}",
            "details": decision,
        }
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if decision["allowed"] else 2


def broker_hook_decision(
    profile: str, tool_name: str, context_tainted: bool = False
) -> dict[str, str] | None:
    """Map a Claude PreToolUse tool name (`mcp__server__tool`) to a permission decision via the
    profile policy. Returns a hookSpecificOutput decision dict for deny/ask, or None to defer to
    the normal permission flow (so the hook only ever *restricts*, never broadens access).

    Note: the PreToolUse input carries no provenance signal, so context_tainted is False here — the
    CaMeL-style tainted-context rule is enforced only on the advisory MCP path where a caller can
    pass context_tainted=True. The hook enforces profile allow/deny + read/write effect."""
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name[len("mcp__") :].split("__", 1)
    if len(parts) != 2:
        return None
    server, tool = parts[0], parts[1]
    d = broker_authorize(profile, server, tool, False, context_tainted)
    if not d["allowed"]:
        return {
            "permissionDecision": "deny",
            "permissionDecisionReason": f"profile '{profile}': {d['reason']} (effect={d['effect']})",
        }
    if d["needs_confirmation"]:
        return {
            "permissionDecision": "ask",
            "permissionDecisionReason": f"profile '{profile}': {tool} is a {d['effect']} action — confirm",
        }
    return None


def cmd_broker_hook(args: argparse.Namespace) -> int:
    """PreToolUse hook entrypoint: read the hook JSON on stdin, enforce the active profile on MCP
    tool calls. No-op (exit 0, no output) when no profile is active or the call isn't an MCP tool."""
    profile = args.profile or os.environ.get("AGENTS_PROFILE", "")
    if not profile:
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    tool_name = str(data.get("tool_name", ""))
    try:
        decision = broker_hook_decision(profile, tool_name)
    except (SystemExit, Exception) as exc:  # noqa: BLE001 — a corrupt/unknown profile must never wedge a session
        # Fail open so the session keeps moving (Claude's compiled deny-list + --strict-mcp-config
        # remain the primary gate), but never silently: a broken broker hook must be observable in
        # the ledger rather than invisible. Best-effort; the failure path must not itself raise.
        try:
            append_ledger(
                {
                    "kind": "broker",
                    "status": "hook-error",
                    "profile": profile,
                    "agent": "hook",
                    "repo": "",
                    "prompt": tool_name,
                    "details": {"error": repr(exc)},
                }
            )
        except Exception:  # noqa: BLE001
            pass
        return 0
    if decision is None:
        return 0
    print(
        json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}})
    )
    try:  # audit is best-effort; a ledger failure must not turn an emitted decision into an error
        append_ledger(
            {
                "kind": "broker",
                "status": decision["permissionDecision"],
                "profile": profile,
                "agent": "hook",
                "repo": "",
                "prompt": tool_name,
                "details": decision,
            }
        )
    except Exception:  # noqa: BLE001
        pass
    return 0


# ---------------------------------------------------------------------------
# Structured query API
#
# These return plain Python data (JSON-serializable lists/dicts) and are the typed boundary the
# daemon (web/agentd.py) imports instead of scraping CLI text. The CLI commands render the same
# data as tab-separated text (default) or JSON (`--json`), so the human and machine surfaces
# never drift.
# ---------------------------------------------------------------------------


def query_profiles() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in profile_files():
        data = load_json(path)
        out.append(
            {
                "name": data["name"],
                "risk": data.get("risk", ""),
                "description": data.get("description", ""),
                "mcp_servers": data.get("mcp_servers", []),
                "allowed_tools": data.get("allowed_tools", []),
                "disallowed_tools": data.get("disallowed_tools", []),
                "confirm": data.get("confirm", []),
            }
        )
    return out


def query_ledger(limit: int = 20) -> list[dict[str, Any]]:
    return iter_ledger()[-limit:]


def query_approvals(status: str = "pending", limit: int = 20) -> list[dict[str, Any]]:
    conn = approval_db()
    expire_approvals(conn)
    rows = conn.execute(
        "SELECT * FROM approvals WHERE (? = 'all' OR status = ?) ORDER BY created_at DESC LIMIT ?",
        (status, status, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def query_queue(status: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    conn = queue_db()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE (? = 'all' OR status = ?) ORDER BY created_at DESC LIMIT ?",
        (status, status, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def query_evals() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(EVALS.glob("*.json")):
        data = load_json(path)
        out.append(
            {
                "id": data["id"],
                "profile": data.get("profile", ""),
                "agent": data.get("agent", ""),
                "description": data.get("description", ""),
            }
        )
    return out


def query_snapshot() -> dict[str, Any]:
    """One aggregate read for the daemon's initial render / status pill."""
    pending = query_approvals("pending", 100)
    running = query_queue("running", 100)
    queued = query_queue("queued", 100)
    chain = verify_ledger()
    return {
        "ts": now(),
        "pending_approvals": len(pending),
        "running_tasks": len(running),
        "queued_tasks": len(queued),
        "ledger_ok": bool(chain.get("ok")),
        "ledger_checked": chain.get("checked", 0),
        "profiles": [p["name"] for p in query_profiles()],
    }


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-control")
    p.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of text (list commands + snapshot)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("snapshot", help="aggregate status snapshot (always JSON)")

    pp = sub.add_parser("profile")
    psub = pp.add_subparsers(dest="profile_cmd", required=True)
    psub.add_parser("list")
    pshow = psub.add_parser("show")
    pshow.add_argument("name")
    psub.add_parser("validate")
    psub.add_parser("compile")
    pcf = psub.add_parser("codex-flags")
    pcf.add_argument("name")

    lp = sub.add_parser("ledger")
    lsub = lp.add_subparsers(dest="ledger_cmd", required=True)
    lr = lsub.add_parser("record")
    lr.add_argument("--kind", required=True)
    lr.add_argument("--status", required=True)
    lr.add_argument("--profile", default="")
    lr.add_argument("--agent", default="")
    lr.add_argument("--repo", default="")
    lr.add_argument("--prompt", default="")
    lr.add_argument("--details", default="{}")
    ll = lsub.add_parser("list")
    ll.add_argument("--limit", type=int, default=20)
    ls = lsub.add_parser("show")
    ls.add_argument("id")
    lsub.add_parser("verify")

    ap = sub.add_parser("approve")
    asub = ap.add_subparsers(dest="approve_cmd", required=True)
    ar = asub.add_parser("request")
    ar.add_argument("--kind", required=True)
    ar.add_argument("--summary", required=True)
    ar.add_argument("--payload", default="{}")
    ar.add_argument("--ttl-hours", type=float, default=DEFAULT_APPROVAL_TTL_HOURS)
    asub.add_parser("expire")
    al = asub.add_parser("list")
    al.add_argument("--status", default="pending")
    al.add_argument("--limit", type=int, default=20)
    ash = asub.add_parser("show")
    ash.add_argument("id")
    aa = asub.add_parser("approve")
    aa.add_argument("id")
    aa.add_argument("--note", default="")
    aj = asub.add_parser("reject")
    aj.add_argument("id")
    aj.add_argument("--note", default="")

    qp = sub.add_parser("queue")
    qsub = qp.add_subparsers(dest="queue_cmd", required=True)
    qa = qsub.add_parser("add")
    qa.add_argument("--repo", required=True)
    qa.add_argument("--profile", required=True)
    qa.add_argument("--agent", default="claude")
    qa.add_argument("--task", required=True)
    qa.add_argument("--timeout", type=int, default=3600)
    qa.add_argument("--max-attempts", type=int, default=1)
    ql = qsub.add_parser("list")
    ql.add_argument("--status", default="all")
    ql.add_argument("--limit", type=int, default=20)
    qs = qsub.add_parser("show")
    qs.add_argument("id")
    qst = qsub.add_parser("start")
    qst.add_argument("id", nargs="?", default="")
    qst.add_argument("--foreground", action="store_true")
    qr = qsub.add_parser("run")
    qr.add_argument("id")
    qf = qsub.add_parser("finish")
    qf.add_argument("id")
    qf.add_argument("--exit-code", type=int, required=True)
    qf.add_argument("--status", default="")
    qc = qsub.add_parser("cancel")
    qc.add_argument("id")
    qretry = qsub.add_parser("retry")
    qretry.add_argument("id")
    qt = qsub.add_parser("tail")
    qt.add_argument("id")
    qt.add_argument("--lines", type=int, default=80)
    qt.add_argument("--follow", action="store_true")
    qsub.add_parser("reconcile")
    qsub.add_parser("worker")

    ep = sub.add_parser("eval")
    esub = ep.add_subparsers(dest="eval_cmd", required=True)
    esub.add_parser("list")
    er = esub.add_parser("run")
    er.add_argument("id")
    er.add_argument("--agent", default="")
    er.add_argument("--profile", default="")
    er.add_argument("--timeout", type=int, default=120)

    bp = sub.add_parser("broker")
    bp.add_argument("--profile", required=True)
    bp.add_argument("--server", required=True)
    bp.add_argument("--tool", required=True)
    bp.add_argument("--mutation", action="store_true")
    bp.add_argument("--context-tainted", action="store_true")

    bh = sub.add_parser("broker-hook")
    bh.add_argument("--profile", default="")
    return p


def main_inner(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "snapshot":
        _print_json(query_snapshot())
        return 0
    if args.cmd == "profile":
        return cmd_profile(args)
    if args.cmd == "ledger":
        return cmd_ledger(args)
    if args.cmd == "approve":
        return cmd_approve(args)
    if args.cmd == "queue":
        return cmd_queue(args)
    if args.cmd == "eval":
        return cmd_eval(args)
    if args.cmd == "broker":
        return cmd_broker(args)
    if args.cmd == "broker-hook":
        return cmd_broker_hook(args)
    raise SystemExit(f"unknown command: {args.cmd}")


def main() -> int:
    return main_inner(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
