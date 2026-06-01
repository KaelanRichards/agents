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
import shutil
import subprocess
import sys
from collections.abc import Sequence


ROOT = pathlib.Path(os.environ.get("AGENTS_HOME", pathlib.Path.home() / ".config" / "agents"))
AUTH = ROOT / "mcp.auth.json"
MCP = ROOT / "mcp.json"
AUTH_STORE = pathlib.Path(os.environ.get("MCP_REMOTE_CONFIG_DIR", "~/.mcp-auth")).expanduser()


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
        expected_args = [
            "-y",
            "mcp-remote@latest",
            meta.get("url"),
            str(meta.get("callback_port")),
            "--host",
            meta.get("callback_host"),
        ]
        if entry.get("type") != "stdio":
            errors.append(f"{name}: expected stdio bridge, got {entry.get('type')!r}")
        if entry.get("command") != "npx":
            errors.append(f"{name}: expected npx command, got {entry.get('command')!r}")
        if entry.get("args") != expected_args:
            errors.append(f"{name}: bridge args mismatch auth={expected_args!r} mcp={entry.get('args')!r}")
        if meta.get("strategy") != "mcp-remote-stdio":
            errors.append(f"{name}: unsupported strategy {meta.get('strategy')!r}")
        if meta.get("token_store") != "~/.mcp-auth":
            errors.append(f"{name}: token_store must be ~/.mcp-auth")
        clients = meta.get("clients", {})
        for required in ("claude", "opencode", "codex"):
            if required not in clients:
                errors.append(f"{name}: missing client auth metadata for {required}")
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
        print(f"{name}\t{meta.get('strategy')}\t{meta.get('url')}\t{', '.join(client_bits)}")
    return 0


def status_one(name: str) -> None:
    meta = require_server(name)
    print(f"== {name} ==")
    print(f"url: {meta.get('url')}")
    print(f"strategy: {meta.get('strategy')}")
    print(f"bridge: npx -y mcp-remote@latest {meta.get('url')} {meta.get('callback_port')} --host {meta.get('callback_host')}")
    print(f"token_store: {AUTH_STORE} ({'present' if AUTH_STORE.exists() else 'missing'})")
    print(f"boundary: {meta.get('account_boundary')}")
    print()
    for client in ("claude", "opencode", "codex"):
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
    print("Principle: sync config everywhere, authenticate once per host with mcp-remote, do not copy token stores.")
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
        print(f"  tunnel:      ssh -L {port}:127.0.0.1:{port} <vm-host> mcp-auth login {name}")
        print("  clients:     Claude, Codex, and OpenCode all reuse the same stdio bridge on that host")
        print()
    return 0


def remote_args(meta: dict) -> list[str]:
    return [
        "npx",
        "-p",
        "mcp-remote@latest",
        "mcp-remote-client",
        str(meta["url"]),
        str(meta["callback_port"]),
        "--host",
        str(meta["callback_host"]),
    ]


def login(args: argparse.Namespace) -> int:
    meta = require_server(args.server)
    cmd = remote_args(meta)
    print(f"Starting OAuth login for {args.server}.")
    print("Open the browser URL that mcp-remote prints. Stop this command after it lists tools.")
    print(f"token_store: {AUTH_STORE}")
    print(f"command: {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode


def vm_login(args: argparse.Namespace) -> int:
    meta = require_server(args.server)
    port = str(meta["callback_port"])
    remote = f"mcp-auth login {args.server}"
    cmd = ["ssh", "-L", f"{port}:127.0.0.1:{port}", args.host, remote]
    print(f"Forwarding local 127.0.0.1:{port} to {args.host}:127.0.0.1:{port}.")
    print("Open the browser URL printed by the remote login; the callback will come back through SSH.")
    print(f"command: {' '.join(cmd)}")
    if args.print_only:
        return 0
    return subprocess.run(cmd, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the MCP OAuth auth contract")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="validate mcp.auth.json against mcp.json")
    sub.add_parser("list", help="list auth-managed MCP servers")

    p_status = sub.add_parser("status", help="show local client auth status and setup commands")
    p_status.add_argument("servers", nargs="*")

    p_plan = sub.add_parser("plan", help="print clean VM setup plan")
    p_plan.add_argument("servers", nargs="*")

    p_login = sub.add_parser("login", help="run mcp-remote OAuth login/test for one server")
    p_login.add_argument("server")

    p_vm = sub.add_parser("vm-login", help="authenticate a VM-hosted bridge through an SSH callback tunnel")
    p_vm.add_argument("server")
    p_vm.add_argument("host")
    p_vm.add_argument("--print-only", action="store_true", help="print the ssh command without running it")

    args = parser.parse_args(argv)
    if args.cmd == "check":
        return check_contract()
    if args.cmd == "list":
        return list_servers()
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
