"""Contract checks for the shared Claude/Codex/Hermes agent setup."""

from __future__ import annotations

import json
import os
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOME = pathlib.Path(os.environ.get("HOME", str(pathlib.Path.home())))

REQUIRED_MCP = {
    "context7",
    "playwright",
    "filesystem",
    "sequential-thinking",
    "github",
    "datadog",
    "bigquery",
    "agents",
    "personal-actions",
    "linear",
}

PERSONAL_ACTION_TOOLS = {
    "personal_slack_send_message",
    "personal_gmail_create_draft",
    "personal_gmail_send_email",
    "personal_gmail_trash_email",
    "personal_calendar_create_event",
    "personal_calendar_update_event",
}


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: pathlib.Path) -> object:
    return json.loads(read(path))


def assert_contains(text: str, needle: str, label: str) -> None:
    assert needle in text, f"{label} missing {needle!r}"


def main() -> None:
    mcp = load_json(ROOT / "mcp.json")
    assert isinstance(mcp, dict)
    servers = mcp.get("mcpServers")
    assert isinstance(servers, dict)
    assert set(servers) == REQUIRED_MCP

    assert servers["linear"]["type"] == "http"
    assert servers["linear"]["url"] == "https://mcp.linear.app/mcp"
    assert servers["datadog"]["type"] == "http"
    assert servers["datadog"]["url"] == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
    assert servers["bigquery"]["type"] == "stdio"
    assert servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")
    assert servers["bigquery"]["args"] == []
    assert servers["github"]["bearer_token_env_var"] == "GITHUB_PAT"
    assert servers["personal-actions"]["command"].endswith("/bin/personal-actions-mcp")

    codex_toml = HOME / ".codex" / "config.toml"
    if codex_toml.exists():
        codex = tomllib.loads(read(codex_toml))
        codex_servers = codex.get("mcp_servers", {})
        assert REQUIRED_MCP.issubset(set(codex_servers)), "Codex config missing required MCP servers"
        assert codex_servers["linear"]["url"] == "https://mcp.linear.app/mcp"
        assert codex_servers["datadog"]["url"] == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
        assert codex_servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")
        assert codex_servers["bigquery"]["args"] == []
        assert codex.get("features", {}).get("experimental_use_rmcp_client") is True

    claude_json = HOME / ".claude.json"
    if claude_json.exists():
        claude = load_json(claude_json)
        assert isinstance(claude, dict)
        claude_servers = claude.get("mcpServers", {})
        assert REQUIRED_MCP.issubset(set(claude_servers)), "Claude config missing required MCP servers"
        assert claude_servers["linear"]["url"] == "https://mcp.linear.app/mcp"
        assert claude_servers["datadog"]["url"] == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
        assert claude_servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")

    hermes_config = HOME / ".hermes" / "config.yaml"
    if hermes_config.exists():
        hermes = read(hermes_config)
        assert_contains(hermes, "agents_readonly:", "Hermes config")
        assert_contains(hermes, "personal_actions:", "Hermes config")
        for tool in PERSONAL_ACTION_TOOLS:
            assert_contains(hermes, f"- {tool}", "Hermes personal_actions tool allowlist")

    server = read(ROOT / "mcp-servers" / "personal-actions" / "server.py")
    for tool in PERSONAL_ACTION_TOOLS:
        assert re.search(rf"def {re.escape(tool)}\(", server), f"personal-actions server missing {tool}"
    assert "/trash" in server
    assert "/delete" not in server

    policy = read(ROOT / "assistant" / "policy.md")
    assert_contains(policy, "exact Gmail message id", "personal assistant policy")
    assert_contains(policy, "permanent Gmail delete endpoint", "personal assistant policy")
    assert_contains(policy, "bulk delete", "personal assistant policy")
    assert_contains(policy, "Datadog MCP", "personal assistant policy")
    assert_contains(policy, "read-only", "personal assistant policy")

    oauth_example = read(ROOT / "assistant" / "windmill" / "oauth.env.example")
    for port in ["8765", "8766", "8767", "8768"]:
        assert_contains(oauth_example, f"http://127.0.0.1:{port}/callback", "Windmill OAuth example")

    print("agent system contract OK")


if __name__ == "__main__":
    main()
