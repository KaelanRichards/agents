"""Focused side-effect and classification tests for mcp-auth status/health."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mcp_auth.py"


def write_json(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        agents_home = tmp / "agents"
        fake_bin = tmp / "bin"
        auth_store = tmp / "mcp-auth"
        marker = tmp / "launched"
        agents_home.mkdir()
        fake_bin.mkdir()
        auth_store.mkdir()

        fake_program = (
            f"#!/bin/sh\nprintf launched > {shlex.quote(str(marker))}\nexit 97\n"
        )
        for name in ("npx", "codex", "claude", "open"):
            path = fake_bin / name
            path.write_text(fake_program, encoding="utf-8")
            path.chmod(0o755)

        bridge_url = "https://bridge.example.invalid/mcp?token=fixture-secret"
        overlay_bridge_url = "https://overlay.example.invalid/mcp?token=overlay-secret"
        native_url = "https://native.example.invalid/mcp"
        write_json(
            agents_home / "mcp.json",
            {
                "mcpServers": {
                    "bridge": {
                        "type": "stdio",
                        "command": "npx",
                        "args": [
                            "-y",
                            "mcp-remote@0.1.38",
                            bridge_url,
                            "3333",
                            "--host",
                            "127.0.0.1",
                        ],
                        "clients": {
                            "codex": {
                                "type": "http",
                                "url": "https://codex.example.invalid/mcp",
                            }
                        },
                    },
                    "native": {"type": "http", "url": native_url},
                    "local": {"type": "stdio", "command": "npx", "args": []},
                    "bearer": {
                        "type": "http",
                        "url": "https://bearer.example.invalid/mcp",
                        "bearer_token_env_var": "TEST_MCP_BEARER",
                    },
                    "disabled": {
                        "type": "stdio",
                        "command": "does-not-exist",
                        "clients": {"codex": {"enabled": False}},
                    },
                    "missing": {"type": "stdio", "command": "does-not-exist"},
                }
            },
        )
        write_json(
            agents_home / "mcp.local.json",
            {
                "mcpServers": {
                    "bridge": {
                        "args": [
                            "-y",
                            "mcp-remote@0.1.39",
                            overlay_bridge_url,
                            "3333",
                            "--host",
                            "127.0.0.1",
                        ],
                        "clients": {
                            "codex": {
                                "url": "https://host.example.invalid/mcp",
                            }
                        },
                    },
                }
            },
        )
        write_json(
            agents_home / "mcp.auth.json",
            {
                "servers": {
                    "bridge": {
                        "url": bridge_url,
                        "strategy": "mcp-remote-stdio",
                        "callback_port": 3333,
                        "callback_host": "127.0.0.1",
                        "token_store": "~/.mcp-auth",
                        "login_command": "mcp-auth login bridge",
                        "clients": {
                            "claude": {"support": "supported-via-stdio-bridge"},
                            "codex": {
                                "support": "supported-via-client-native-http-oauth",
                                "url": "https://host.example.invalid/mcp",
                            },
                        },
                    },
                    "native": {
                        "url": native_url,
                        "strategy": "client-native-http-oauth",
                        "token_store": "client-managed",
                        "login_command": "codex mcp login native",
                        "clients": {
                            "claude": {
                                "support": "supported-via-client-native-http-oauth"
                            },
                            "codex": {
                                "support": "supported-via-client-native-http-oauth"
                            },
                        },
                    },
                }
            },
        )

        env = os.environ.copy()
        env.update(
            {
                "AGENTS_HOME": str(agents_home),
                "HOME": str(tmp / "home"),
                "MCP_REMOTE_CONFIG_DIR": str(auth_store),
                "PATH": str(fake_bin),
            }
        )

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(SCRIPT), *args],
                check=False,
                text=True,
                capture_output=True,
                env=env,
            )

        contract = run("check")
        assert contract.returncode == 0, contract.stderr
        assert not marker.exists(), (
            "contract check launched a client, bridge, or browser"
        )

        status = run("status", "bridge", "native")
        assert status.returncode == 0, status.stderr
        assert "claude: supported-via-stdio-bridge" in status.stdout
        assert "stdio npx" in status.stdout
        assert (
            "https://overlay.example.invalid/<redacted-path>?<redacted-query>"
            in status.stdout
        )
        assert "http https://host.example.invalid/<redacted-path>" in status.stdout
        assert "result:" not in status.stdout
        assert "fixture-secret" not in status.stdout
        assert "overlay-secret" not in status.stdout
        assert not marker.exists(), "status launched a client, bridge, or browser"

        healthy = run(
            "health",
            "--client",
            "codex",
            "--offline",
            "--json",
            "bridge",
            "native",
            "local",
            "bearer",
            "disabled",
        )
        assert healthy.returncode == 0, healthy.stderr
        data = json.loads(healthy.stdout)
        statuses = {item["name"]: item["status"] for item in data["results"]}
        assert statuses == {
            "bridge": "unverified",
            "native": "unverified",
            "local": "ready",
            "bearer": "auth-required",
            "disabled": "disabled",
        }
        assert data["summary"]["broken"] == 0

        broken = run("health", "--client", "codex", "--offline", "--json")
        assert broken.returncode == 1
        broken_data = json.loads(broken.stdout)
        assert broken_data["summary"]["broken"] == 1
        assert not marker.exists(), "health launched a client, bridge, or browser"

        uncached = run("health", "--client", "claude", "--offline", "--json", "bridge")
        assert json.loads(uncached.stdout)["results"][0]["status"] == "auth-required"
        digest = hashlib.md5(
            overlay_bridge_url.encode(), usedforsecurity=False
        ).hexdigest()
        version_store = auth_store / "mcp-remote-0.1.39"
        version_store.mkdir()
        (version_store / f"{digest}_tokens.json").touch()
        cached = run("health", "--client", "claude", "--offline", "--json", "bridge")
        assert cached.returncode == 0
        assert json.loads(cached.stdout)["results"][0]["status"] == "ready"
        assert not marker.exists(), "cache inspection launched a process"

    print("mcp auth health tests OK")


if __name__ == "__main__":
    main()
