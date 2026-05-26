#!/usr/bin/env python3
"""Local control-plane helpers for profiles, runs, queue, approvals, and evals."""

from __future__ import annotations

import argparse
import datetime as dt
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


AH = Path(os.environ.get("AGENTS_HOME", str(Path.home() / ".config/agents"))).expanduser()
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
    code, out = run(["jj", "log", "-r", "@", "--no-graph", "-T", "change_id ++ ' ' ++ commit_id.short()"], repo, 15)
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


def ledger_path() -> Path:
    ensure_state()
    path = STATE / "runs" / f"{today()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_ledger(entry: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "id": entry.get("id") or str(uuid.uuid4()),
        "ts": entry.get("ts") or now(),
        **entry,
    }
    with ledger_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


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
        entries = iter_ledger()[-args.limit :]
        for e in entries:
            print(f"{e.get('ts','')}\t{e.get('id','')}\t{e.get('kind','')}\t{e.get('status','')}\t{e.get('profile','')}\t{e.get('repo','')}")
        return 0
    if args.ledger_cmd == "show":
        for e in iter_ledger():
            if e.get("id") == args.id:
                print(json.dumps(e, indent=2, sort_keys=True))
                return 0
        raise SystemExit(f"run not found: {args.id}")
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
    return conn


def cmd_approve(args: argparse.Namespace) -> int:
    conn = approval_db()
    if args.approve_cmd == "request":
        aid = str(uuid.uuid4())
        payload = args.payload or "{}"
        json.loads(payload)
        conn.execute(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, 'pending', '')",
            (aid, now(), now(), args.kind, args.summary, payload),
        )
        conn.commit()
        append_ledger({"kind": "approval", "status": "pending", "profile": "", "agent": "", "repo": "", "prompt": args.summary, "details": {"approval_id": aid, "approval_kind": args.kind}})
        print(aid)
        return 0
    if args.approve_cmd == "list":
        rows = conn.execute(
            "SELECT * FROM approvals WHERE (? = 'all' OR status = ?) ORDER BY created_at DESC LIMIT ?",
            (args.status, args.status, args.limit),
        ).fetchall()
        for r in rows:
            print(f"{r['created_at']}\t{r['id']}\t{r['status']}\t{r['kind']}\t{r['summary']}")
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
        append_ledger({"kind": "approval", "status": status, "profile": "", "agent": "", "repo": "", "prompt": row["id"], "details": {"note": args.note or ""}})
        print(status)
        return 0
    raise SystemExit("missing approval command")


def lookup_approval(conn: sqlite3.Connection, approval_id: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row:
        return row
    rows = conn.execute("SELECT * FROM approvals WHERE id LIKE ?", (approval_id + "%",)).fetchall()
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
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


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
        append_ledger({"kind": "queue", "status": "queued", "profile": args.profile, "agent": args.agent, "repo": str(repo), "prompt": args.task, "details": {"queue_id": qid, "workspace": str(ws)}})
        print(qid)
        return 0
    if args.queue_cmd == "list":
        rows = conn.execute(
            "SELECT * FROM tasks WHERE (? = 'all' OR status = ?) ORDER BY created_at DESC LIMIT ?",
            (args.status, args.status, args.limit),
        ).fetchall()
        for r in rows:
            print(f"{r['created_at']}\t{r['id']}\t{r['status']}\t{r['profile']}\t{r['agent']}\t{r['repo']}\t{r['task'][:80]}")
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
    return conn.execute("SELECT * FROM tasks WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()


def lookup_queue_task(conn: sqlite3.Connection, qid: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (qid,)).fetchone()
    if row:
        return row
    rows = conn.execute("SELECT * FROM tasks WHERE id LIKE ?", (qid + "%",)).fetchall()
    if len(rows) > 1:
        raise SystemExit(f"task id prefix is ambiguous: {qid}")
    return rows[0] if rows else None


def start_queue_task(conn: sqlite3.Connection, row: sqlite3.Row, foreground: bool) -> None:
    if row["status"] not in {"queued", "failed", "canceled"}:
        raise SystemExit(f"task {row['id']} is {row['status']}, not queued")
    if int(row["attempts"]) >= int(row["max_attempts"]):
        raise SystemExit(f"task {row['id']} has exhausted attempts ({row['attempts']}/{row['max_attempts']})")
    repo = Path(row["repo"])
    ws = Path(row["workspace"])
    log = Path(row["log"])
    log.parent.mkdir(parents=True, exist_ok=True)
    if not ws.exists():
        ws.parent.mkdir(parents=True, exist_ok=True)
        code, out = run(["jj", "-R", str(repo), "workspace", "add", str(ws)], timeout=120)
        if code != 0:
            conn.execute("UPDATE tasks SET status = 'failed', updated_at = ? WHERE id = ?", (now(), row["id"]))
            conn.commit()
            raise SystemExit(out)
    conn.execute(
        "UPDATE tasks SET status = 'running', updated_at = ?, attempts = attempts + 1, cancel_requested = 0 WHERE id = ?",
        (now(), row["id"]),
    )
    conn.commit()
    append_ledger({"kind": "queue", "status": "running", "profile": row["profile"], "agent": row["agent"], "repo": row["repo"], "prompt": row["task"], "details": {"queue_id": row["id"], "workspace": str(ws), "session": row["session"]}})
    if row["agent"] == "noop" or foreground:
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (row["id"],)).fetchone()
        assert updated
        run_queue_task(conn, updated)
        return
    runner = AH / "scripts" / "agent_control.py"
    tmux_cmd = f"python3 {shlex.quote(str(runner))} queue run {shlex.quote(row['id'])}"
    code, out = run(["tmux", "new-session", "-d", "-s", row["session"], tmux_cmd], timeout=30)
    if code != 0:
        raise SystemExit(out)
    print(f"started {row['id']} session={row['session']} log={log}")


def run_queue_task(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    ws = Path(row["workspace"])
    log = Path(row["log"])
    command = agent_command(row["agent"], row["task"])
    timeout = int(row["timeout_seconds"])
    code, out = shell(command, ws, timeout=timeout)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(out + "\n", encoding="utf-8")
    cancel_row = conn.execute("SELECT cancel_requested FROM tasks WHERE id = ?", (row["id"],)).fetchone()
    status = "canceled" if cancel_row and int(cancel_row["cancel_requested"]) else ("done" if code == 0 else "failed")
    finish_queue_task(conn, row["id"], code, status)
    print(f"{status}: {row['id']} log={log}")


def finish_queue_task(conn: sqlite3.Connection, qid: str, exit_code: int, status: str = "") -> None:
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
            "details": {"queue_id": row["id"], "exit_code": int(exit_code), "log": row["log"]},
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
    append_ledger({"kind": "queue", "status": "canceled", "profile": row["profile"], "agent": row["agent"], "repo": row["repo"], "prompt": row["task"], "details": {"queue_id": row["id"]}})
    print(f"canceled: {row['id']}")


def retry_queue_task(conn: sqlite3.Connection, qid: str) -> None:
    row = lookup_queue_task(conn, qid)
    if not row:
        raise SystemExit(f"task not found: {qid}")
    if row["status"] not in {"failed", "canceled"}:
        raise SystemExit(f"task {qid} is {row['status']}; only failed/canceled tasks can be retried")
    conn.execute(
        "UPDATE tasks SET status = 'queued', updated_at = ?, completed_at = '', exit_code = NULL, cancel_requested = 0 WHERE id = ?",
        (now(), row["id"]),
    )
    conn.commit()
    append_ledger({"kind": "queue", "status": "retried", "profile": row["profile"], "agent": row["agent"], "repo": row["repo"], "prompt": row["task"], "details": {"queue_id": row["id"]}})
    print(f"queued: {row['id']}")


def tail_queue_task(conn: sqlite3.Connection, qid: str, lines: int, follow: bool) -> None:
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
        current = conn.execute("SELECT status FROM tasks WHERE id = ?", (qid,)).fetchone()
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
        if log.exists() and "Traceback" not in log.read_text(encoding="utf-8", errors="replace")[-4000:]:
            status = "done" if row["agent"] == "noop" else "failed"
        finish_queue_task(conn, row["id"], exit_code, status)
        print(f"reconciled {row['id']} -> {status}")


def agent_command(agent: str, task: str) -> str:
    quoted = shlex.quote(task)
    if agent == "noop":
        return f"printf '%s\\n' {quoted}"
    if agent == "codex":
        return f"codex exec --full-auto {quoted}"
    if agent == "claude":
        return f"claude -p --permission-mode auto {quoted}"
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
}


def tool_words(tool: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", tool.lower()) if part}


def infer_mutation(tool: str, mutation: bool) -> bool:
    if mutation:
        return True
    return bool(tool_words(tool) & MUTATING_TOOL_WORDS)


def capability_matches(capability: str, server: str, tool: str, inferred_mutation: bool) -> bool:
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


def capability_list_matches(capabilities: list[str], server: str, tool: str, inferred_mutation: bool) -> bool:
    return any(capability_matches(capability, server, tool, inferred_mutation) for capability in capabilities)


def cmd_eval(args: argparse.Namespace) -> int:
    if args.eval_cmd == "list":
        for path in sorted(EVALS.glob("*.json")):
            data = load_json(path)
            print(f"{data['id']}\t{data.get('profile','')}\t{data.get('description','')}")
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
        append_ledger({"kind": "eval", "status": "started", "profile": profile, "agent": agent, "repo": str(repo), "prompt": task["prompt"], "details": {"eval_id": task["id"]}})
        if agent != "noop":
            qid_code = main_inner(["queue", "add", "--repo", str(repo), "--profile", profile, "--agent", agent, "--task", task["prompt"]])
            return qid_code
        code, out = shell(task.get("success_command", "true"), repo, timeout=args.timeout)
        status = "passed" if code == 0 else "failed"
        append_ledger({"kind": "eval", "status": status, "profile": profile, "agent": agent, "repo": str(repo), "prompt": task["prompt"], "details": {"eval_id": task["id"], "exit_code": code, "output": out[-4000:]}})
        print(out)
        print(f"eval {task['id']}: {status}")
        return code
    raise SystemExit("missing eval command")


def broker_authorize(profile_name: str, server: str, tool: str, mutation: bool) -> dict[str, Any]:
    profile = load_profile(profile_name)
    allowed_server = server in profile["mcp_servers"]
    inferred_mutation = infer_mutation(tool, mutation)
    disallowed = capability_list_matches(profile["disallowed_tools"], server, tool, inferred_mutation)
    allowed_tool = capability_list_matches(profile["allowed_tools"], server, tool, inferred_mutation)
    confirm_tool = capability_list_matches(profile["confirm"], server, tool, inferred_mutation)
    if confirm_tool:
        allowed_tool = True
    needs_confirm = inferred_mutation or confirm_tool
    allowed = allowed_server and allowed_tool and not disallowed
    if inferred_mutation and profile["risk"] in {"high", "critical"}:
        needs_confirm = True
    return {
        "allowed": allowed,
        "needs_confirmation": needs_confirm,
        "profile": profile_name,
        "server": server,
        "tool": tool,
        "mutation": inferred_mutation,
        "caller_marked_mutation": mutation,
        "reason": "ok" if allowed else "server/tool denied by profile",
    }


def cmd_broker(args: argparse.Namespace) -> int:
    decision = broker_authorize(args.profile, args.server, args.tool, args.mutation)
    append_ledger({"kind": "broker", "status": "allowed" if decision["allowed"] else "denied", "profile": args.profile, "agent": "", "repo": "", "prompt": f"{args.server}.{args.tool}", "details": decision})
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if decision["allowed"] else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-control")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("profile")
    psub = pp.add_subparsers(dest="profile_cmd", required=True)
    psub.add_parser("list")
    pshow = psub.add_parser("show")
    pshow.add_argument("name")
    psub.add_parser("validate")
    psub.add_parser("compile")

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

    ap = sub.add_parser("approve")
    asub = ap.add_subparsers(dest="approve_cmd", required=True)
    ar = asub.add_parser("request")
    ar.add_argument("--kind", required=True)
    ar.add_argument("--summary", required=True)
    ar.add_argument("--payload", default="{}")
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
    return p


def main_inner(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
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
    raise SystemExit(f"unknown command: {args.cmd}")


def main() -> int:
    return main_inner(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
