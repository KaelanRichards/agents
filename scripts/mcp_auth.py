#!/usr/bin/env python3
"""MCP auth control-plane helper.

This intentionally does not export/import OAuth tokens. OAuth-backed remote MCPs use mcp-remote
as a stdio bridge, so auth state is host-local in ~/.mcp-auth and shared by every
stdio-compatible client that launches the same bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence


ROOT = pathlib.Path(
    os.environ.get("AGENTS_HOME", pathlib.Path.home() / ".config" / "agents")
)
AUTH = ROOT / "mcp.auth.json"
MCP = ROOT / "mcp.json"
AUTH_STORE = pathlib.Path(
    os.environ.get("MCP_REMOTE_CONFIG_DIR", "~/.mcp-auth")
).expanduser()


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_quiet(cmd: Sequence[str], timeout: int = 8) -> tuple[int, str]:
    if not shutil.which(cmd[0]):
        return 127, f"{cmd[0]} not on PATH"
    try:
        proc = subprocess.run(
            list(cmd),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd)} timed out"
    return proc.returncode, proc.stdout.strip()


def auth_servers() -> dict:
    data = load_json(AUTH)
    servers = data.get("servers", {})
    if not isinstance(servers, dict):
        raise SystemExit("mcp.auth.json: servers must be an object")
    return servers


def canonical_servers() -> dict:
    data = load_json(MCP)
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit("mcp.json: mcpServers must be an object")
    return servers


def require_server(name: str) -> dict:
    servers = auth_servers()
    if name not in servers:
        known = ", ".join(sorted(servers))
        raise SystemExit(f"unknown auth-managed MCP server {name!r}; known: {known}")
    return servers[name]


def check_contract() -> int:
    auth = auth_servers()
    mcp = canonical_servers()
    errors: list[str] = []
    for name, meta in sorted(auth.items()):
        if name not in mcp:
            errors.append(f"{name}: present in mcp.auth.json but missing from mcp.json")
            continue
        entry = mcp[name]
        strategy = meta.get("strategy")
        if strategy == "mcp-remote-stdio":
            if entry.get("type") != "stdio":
                errors.append(
                    f"{name}: expected stdio bridge, got {entry.get('type')!r}"
                )
            args = entry.get("args") or []
            # The mcp-remote version is PINNED in mcp.json. Assert it's a pinned mcp-remote@<version>
            # (never @latest — @latest re-resolves every launch and breaks ~/.mcp-auth lockfile
            # coordination, causing slow starts + duplicate OAuth prompts) and that the URL / callback
            # port / host match the auth contract. The exact version lives only in mcp.json — not
            # copied here — so it can't drift.
            expected_tail = [
                meta.get("url"),
                str(meta.get("callback_port")),
                "--host",
                meta.get("callback_host"),
            ]
            if entry.get("command") != "npx":
                errors.append(
                    f"{name}: expected npx command, got {entry.get('command')!r}"
                )
            elif not (
                len(args) == 6
                and args[0] == "-y"
                and isinstance(args[1], str)
                and args[1].startswith("mcp-remote@")
                and args[1] != "mcp-remote@latest"
                and args[2:] == expected_tail
            ):
                errors.append(
                    f"{name}: bridge args mismatch — expected ['-y','mcp-remote@<pinned>',*{expected_tail!r}], got {args!r}"
                )
        elif strategy == "mcp-remote-wrapper":
            if entry.get("type") != "stdio":
                errors.append(
                    f"{name}: expected stdio wrapper, got {entry.get('type')!r}"
                )
            if entry.get("command") != meta.get("command"):
                errors.append(
                    f"{name}: wrapper command mismatch auth={meta.get('command')!r} mcp={entry.get('command')!r}"
                )
            if entry.get("args", []) != meta.get("args", []):
                errors.append(
                    f"{name}: wrapper args mismatch auth={meta.get('args', [])!r} mcp={entry.get('args', [])!r}"
                )
        elif strategy == "client-native-http-oauth":
            if entry.get("type") != "http":
                errors.append(
                    f"{name}: expected http remote server, got {entry.get('type')!r}"
                )
            if entry.get("url") != meta.get("url"):
                errors.append(
                    f"{name}: URL mismatch auth={meta.get('url')!r} mcp={entry.get('url')!r}"
                )
            if entry.get("headers") or entry.get("bearer_token_env_var"):
                errors.append(
                    f"{name}: client-native OAuth must not force static shared auth"
                )
        else:
            errors.append(f"{name}: unsupported strategy {meta.get('strategy')!r}")
        expected_store = (
            "client-managed"
            if strategy == "client-native-http-oauth"
            else "~/.mcp-auth"
        )
        if meta.get("token_store") != expected_store:
            errors.append(f"{name}: token_store must be {expected_store}")
        clients = meta.get("clients", {})
        for required in ("claude", "codex"):
            if required not in clients:
                errors.append(f"{name}: missing client auth metadata for {required}")
    # Pinned mcp-remote versions must have a populated OAuth store, or unattended startup re-auths
    # (the failure mode that hangs Codex on Slack). A bump without `mcp-auth migrate` orphans these.
    for version in sorted(pinned_remote_versions()):
        if not version_store(version).exists():
            errors.append(
                f"mcp-remote {version}: no {version_store(version).name}/ OAuth store "
                f"(version bump orphaned auth — run: mcp-auth migrate)"
            )
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"OK: {len(auth)} MCP auth contract(s) match mcp.json")
    return 0


def list_servers() -> int:
    for name, meta in sorted(auth_servers().items()):
        client_bits = []
        for client, cfg in sorted(meta.get("clients", {}).items()):
            client_bits.append(f"{client}:{cfg.get('support', 'unknown')}")
        print(
            f"{name}\t{meta.get('strategy')}\t{meta.get('url')}\t{', '.join(client_bits)}"
        )
    return 0


def status_one(name: str) -> None:
    meta = require_server(name)
    print(f"== {name} ==")
    print(f"url: {meta.get('url')}")
    print(f"strategy: {meta.get('strategy')}")
    if meta.get("strategy") == "client-native-http-oauth":
        print(f"login: {meta.get('login_command')}")
    elif meta.get("strategy") == "mcp-remote-wrapper":
        print(f"bridge: {meta.get('command')}")
    else:
        print(
            f"bridge: npx -y {remote_pin(name)} {meta.get('url')} {meta.get('callback_port')} --host {meta.get('callback_host')}"
        )
    if meta.get("token_store") == "client-managed":
        print("token_store: client-managed")
    else:
        print(
            f"token_store: {AUTH_STORE} ({'present' if AUTH_STORE.exists() else 'missing'})"
        )
    print(f"boundary: {meta.get('account_boundary')}")
    if meta.get("host_requirements"):
        print(f"host_requirements: {meta.get('host_requirements')}")
    print()
    for client in ("claude", "codex"):
        cfg = meta.get("clients", {}).get(client, {})
        support = cfg.get("support", "unknown")
        verify = cfg.get("verify_command", "")
        print(f"{client}: {support}")
        if verify:
            rc, out = run_quiet(verify.split())
            first = out.splitlines()[0] if out else "(no output)"
            print(f"  verify: {verify}")
            print(f"  result: rc={rc} {first}")
        setup = cfg.get("setup")
        if setup:
            print(f"  setup: {setup}")
        print()


def status(args: argparse.Namespace) -> int:
    names = args.servers or sorted(auth_servers())
    for idx, name in enumerate(names):
        if idx:
            print()
        status_one(name)
    return 0


def plan(args: argparse.Namespace) -> int:
    names = args.servers or sorted(auth_servers())
    print("MCP OAuth setup plan")
    print()
    print(
        "Principle: sync config everywhere, authenticate once per host with mcp-remote, do not copy token stores."
    )
    print()
    print("On every target host:")
    print("  cd ~/.config/agents")
    print("  jj git fetch && mcp-sync && agents-sync")
    for name in names:
        print(f"  mcp-auth login {name}")
    print("  mcp-auth status " + " ".join(names))
    print()
    print("From your laptop to authenticate a VM with your local browser:")
    for name in names:
        meta = require_server(name)
        port = meta.get("callback_port")
        print(f"{name}:")
        print(f"  url: {meta.get('url')}")
        print(f"  local login: mcp-auth login {name}")
        print(f"  VM login:    mcp-auth vm-login {name} <vm-host>")
        print(
            f"  tunnel:      ssh -L {port}:127.0.0.1:{port} <vm-host> mcp-auth login {name}"
        )
        print(
            "  clients:     Claude, Codex, and OpenCode all reuse the same stdio bridge on that host"
        )
        print()
    return 0


def expand_host_path(value: str) -> str:
    return value.replace("$AGENTS_HOME", str(ROOT)).replace(
        "$HOME", str(pathlib.Path.home())
    )


def remote_pin(name: str) -> str:
    """The pinned mcp-remote@<version> token for a server, read from mcp.json (the single source of
    the version). Login must use the SAME version as the runtime bridge so the ~/.mcp-auth token it
    writes is read back by the identical client version (a mismatch triggers re-auth)."""
    entry = canonical_servers().get(name, {})
    for a in entry.get("args", []):
        if isinstance(a, str) and a.startswith("mcp-remote@"):
            return a
    # The Slack wrapper (and any future wrapper) hides its mcp-remote@<ver> behind a bin/ script;
    # fall back to scanning the wrapper source so version-store migration covers it too.
    command = entry.get("command")
    if isinstance(command, str):
        script = pathlib.Path(expand_host_path(command))
        try:
            for tok in script.read_text(encoding="utf-8").split():
                tok = tok.strip("\"'")
                if tok.startswith("mcp-remote@") and tok != "mcp-remote@latest":
                    return tok
        except OSError:
            pass
    return "mcp-remote@latest"


def pinned_remote_versions() -> set[str]:
    """Distinct mcp-remote versions any bridge in mcp.json pins (e.g. {"0.1.38"}). mcp-remote stores
    its OAuth cache under ~/.mcp-auth/mcp-remote-<version>/, so a version bump silently orphans every
    cached login — these are the version dirs that MUST exist for unattended startup to skip re-auth.
    """
    versions: set[str] = set()
    for name in canonical_servers():
        pin = remote_pin(name)
        if pin != "mcp-remote@latest" and "@" in pin:
            versions.add(pin.split("@", 1)[1])
    return versions


def version_store(version: str) -> pathlib.Path:
    return AUTH_STORE / f"mcp-remote-{version}"


def existing_stores() -> list[pathlib.Path]:
    """Existing ~/.mcp-auth/mcp-remote-* dirs, newest first (by mtime)."""
    if not AUTH_STORE.exists():
        return []
    dirs = [p for p in AUTH_STORE.glob("mcp-remote-*") if p.is_dir()]
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)


def migrate(args: argparse.Namespace) -> int:
    """Ensure every pinned mcp-remote version has a populated OAuth store, copying from the newest
    existing store when a version dir is missing. Idempotent; safe to run on every sync."""
    wanted = pinned_remote_versions()
    if not wanted:
        print("no pinned mcp-remote bridges — nothing to migrate")
        return 0
    stores = existing_stores()
    rc = 0
    for version in sorted(wanted):
        dst = version_store(version)
        if dst.exists():
            print(f"ok: {dst.name} present")
            continue
        src = next((s for s in stores if s != dst), None)
        if src is None:
            print(
                f"MISSING: {dst.name} and no prior store to migrate from — run: mcp-auth login <server>",
                file=sys.stderr,
            )
            rc = 1
            continue
        if args.dry_run:
            print(f"would copy {src.name} -> {dst.name}")
            continue
        shutil.copytree(src, dst)
        print(f"migrated {src.name} -> {dst.name} ({len(list(dst.iterdir()))} entries)")
    return rc


def remote_args(name: str, meta: dict) -> list[str]:
    if meta.get("strategy") == "mcp-remote-wrapper":
        entry = canonical_servers()[name]
        command = expand_host_path(entry["command"])
        return [command, *entry.get("args", [])]
    return [
        "npx",
        "-y",
        "-p",
        remote_pin(name),
        "mcp-remote-client",
        str(meta["url"]),
        str(meta["callback_port"]),
        "--host",
        str(meta["callback_host"]),
    ]


def login(args: argparse.Namespace) -> int:
    meta = require_server(args.server)
    cmd = remote_args(args.server, meta)
    print(f"Starting OAuth login for {args.server}.")
    print(
        "Open the browser URL that mcp-remote prints. Stop this command after it lists tools."
    )
    print(f"token_store: {AUTH_STORE}")
    print(f"command: {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode


def vm_login(args: argparse.Namespace) -> int:
    meta = require_server(args.server)
    port = str(meta["callback_port"])
    remote = "zsh -lc " + shlex.quote(f"mcp-auth login {shlex.quote(args.server)}")
    cmd = ["ssh", "-L", f"{port}:127.0.0.1:{port}", args.host, remote]
    print(f"Forwarding local 127.0.0.1:{port} to {args.host}:127.0.0.1:{port}.")
    print(
        "Open the browser URL printed by the remote login; the callback will come back through SSH."
    )
    print(f"command: {' '.join(cmd)}")
    if args.print_only:
        return 0
    return subprocess.run(cmd, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the MCP OAuth auth contract")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="validate mcp.auth.json against mcp.json")
    sub.add_parser("list", help="list auth-managed MCP servers")

    p_migrate = sub.add_parser(
        "migrate",
        help="ensure each pinned mcp-remote version has a populated ~/.mcp-auth store",
    )
    p_migrate.add_argument(
        "--dry-run", action="store_true", help="report actions without copying"
    )

    p_status = sub.add_parser(
        "status", help="show local client auth status and setup commands"
    )
    p_status.add_argument("servers", nargs="*")

    p_plan = sub.add_parser("plan", help="print clean VM setup plan")
    p_plan.add_argument("servers", nargs="*")

    p_login = sub.add_parser(
        "login", help="run mcp-remote OAuth login/test for one server"
    )
    p_login.add_argument("server")

    p_vm = sub.add_parser(
        "vm-login",
        help="authenticate a VM-hosted bridge through an SSH callback tunnel",
    )
    p_vm.add_argument("server")
    p_vm.add_argument("host")
    p_vm.add_argument(
        "--print-only",
        action="store_true",
        help="print the ssh command without running it",
    )

    args = parser.parse_args(argv)
    if args.cmd == "check":
        return check_contract()
    if args.cmd == "list":
        return list_servers()
    if args.cmd == "migrate":
        return migrate(args)
    if args.cmd == "status":
        return status(args)
    if args.cmd == "plan":
        return plan(args)
    if args.cmd == "login":
        return login(args)
    if args.cmd == "vm-login":
        return vm_login(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
