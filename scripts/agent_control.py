#!/usr/bin/env python3
"""Local control-plane helpers: permission profiles + the profile-broker (advisory CLI + PreToolUse hook)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any


AH = Path(
    os.environ.get("AGENTS_HOME", str(Path.home() / ".config/agents"))
).expanduser()
STATE = Path(os.environ.get("AGENTS_STATE", str(AH / "state"))).expanduser()
PROFILES = AH / "profiles"
GENERATED = AH / "generated" / "profiles"


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
    code, out = run(
        [
            "jj",
            # Snapshotting the working copy on a read can race a concurrent jj mutation and make jj
            # discard the divergent op (silently dropping an agent commit / workspace add). A read
            # must never mutate: --ignore-working-copy reads the recorded @ without snapshotting.
            "--ignore-working-copy",
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
    if "guidance" in data and not isinstance(data["guidance"], list):
        raise SystemExit(f"{path}: guidance must be list")


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
    guidance = profile.get("guidance") or []
    if guidance:
        summary += (
            "\nOperational guidance:\n"
            + "\n".join(f"- {item}" for item in guidance)
            + "\n"
        )
    (GENERATED / "claude").mkdir(parents=True, exist_ok=True)
    (GENERATED / "claude" / f"{name}.md").write_text(summary, encoding="utf-8")
    toml = [
        f'name = "{name}"',
        f'description = "{profile["description"]}"',
        f'risk = "{profile["risk"]}"',
        "mcp_servers = " + json.dumps(profile["mcp_servers"]),
        "allowed_tools = " + json.dumps(profile["allowed_tools"]),
        "disallowed_tools = " + json.dumps(profile["disallowed_tools"]),
        "confirm = " + json.dumps(profile["confirm"]),
        "skills = " + json.dumps(profile["skills"]),
        "guidance = " + json.dumps(guidance),
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
    """Native Codex containment for a profile: --sandbox + --ask-for-approval, PLUS per-profile MCP
    server subsetting. Codex has no --strict-mcp-config, but it accepts `-c mcp_servers.<id>.enabled
    =false` overrides, so we disable every MCP server the profile does not grant — making the server
    subset a real boundary on Codex too (parity with Claude's --strict-mcp-config), not just advice."""
    fs_mode = (profile.get("filesystem") or {}).get("mode")
    sandbox = "workspace-write" if fs_mode == "workspace-write" else "read-only"
    approval = (
        "untrusted" if profile.get("risk") in {"high", "critical"} else "on-request"
    )
    args = ["--sandbox", sandbox, "--ask-for-approval", approval]
    # Disable every known MCP server not granted by the profile. Quote the server id so hyphenated
    # names (slack-dm, personal-actions, …) parse as a single TOML key.
    allow_servers = set(profile["mcp_servers"])
    for srv in sorted(set(claude_mcp_servers()) - allow_servers):
        args += ["-c", f'mcp_servers."{srv}".enabled=false']
    return args


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
    "slack_read": "slack",
    "cloudflare_read": "cloudflare",
}

WRITE_CAPABILITY_SERVERS = {
    "slack_write": "slack",
    "cloudflare_write": "cloudflare",
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
    # agents MCP — broker / policy query tools (read-only)
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
    if capability in WRITE_CAPABILITY_SERVERS:
        expected_server = WRITE_CAPABILITY_SERVERS[capability]
        return server == expected_server and inferred_mutation
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


def broker_authorize(
    profile_name: str,
    server: str,
    tool: str,
    mutation: bool,
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
    return {
        "allowed": allowed,
        "needs_confirmation": needs_confirm,
        "profile": profile_name,
        "server": server,
        "tool": tool,
        "effect": effect,
        "mutation": inferred_mutation,
        "caller_marked_mutation": mutation,
        "reason": reason,
    }


def cmd_broker(args: argparse.Namespace) -> int:
    decision = broker_authorize(args.profile, args.server, args.tool, args.mutation)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if decision["allowed"] else 2


def broker_hook_decision(profile: str, tool_name: str) -> dict[str, str] | None:
    """Map a Claude PreToolUse tool name (`mcp__server__tool`) to a permission decision via the
    profile policy. Returns a hookSpecificOutput decision dict for deny/ask, or None to defer to
    the normal permission flow (so the hook only ever *restricts*, never broadens access).
    The hook enforces profile allow/deny + read/write effect."""
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name[len("mcp__") :].split("__", 1)
    if len(parts) != 2:
        return None
    server, tool = parts[0], parts[1]
    d = broker_authorize(profile, server, tool, False)
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
        # Fail CLOSED for MCP tool calls: if the broker can't evaluate the active profile
        # (unknown/corrupt profile, validation error), the per-tool read/write gate is the only
        # thing standing between an MCP write tool and the session — denying is the safe default.
        # Non-MCP calls aren't the broker's concern, so stay out of the way (Claude's compiled
        # deny-list + --strict-mcp-config remain the primary gate there). The normal launch path
        # validates the profile up front (agentp), so this only fires on genuine mid-session breakage.
        if tool_name.startswith("mcp__"):
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": (
                                f"profile '{profile}': broker could not evaluate this MCP call "
                                f"({exc}); denying (fail-closed)."
                            ),
                        }
                    }
                )
            )
        return 0
    if decision is None:
        return 0
    print(
        json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}})
    )
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

    pp = sub.add_parser("profile")
    psub = pp.add_subparsers(dest="profile_cmd", required=True)
    psub.add_parser("list")
    pshow = psub.add_parser("show")
    pshow.add_argument("name")
    psub.add_parser("validate")
    psub.add_parser("compile")
    pcf = psub.add_parser("codex-flags")
    pcf.add_argument("name")

    bp = sub.add_parser("broker")
    bp.add_argument("--profile", required=True)
    bp.add_argument("--server", required=True)
    bp.add_argument("--tool", required=True)
    bp.add_argument("--mutation", action="store_true")

    bh = sub.add_parser("broker-hook")
    bh.add_argument("--profile", default="")
    return p


def main_inner(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "profile":
        return cmd_profile(args)
    if args.cmd == "broker":
        return cmd_broker(args)
    if args.cmd == "broker-hook":
        return cmd_broker_hook(args)
    raise SystemExit(f"unknown command: {args.cmd}")


def main() -> int:
    return main_inner(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
