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
    "sentry",
    "bigquery",
    "agents",
    "agent-broker",
    "personal-actions",
    "linear",
    "slack-dm",
}

PERSONAL_ACTION_TOOLS = {
    "personal_slack_send_message",
    "personal_slack_search_messages",
    "personal_gmail_search_messages",
    "personal_gmail_get_message",
    "personal_gmail_create_draft",
    "personal_gmail_send_email",
    "personal_gmail_trash_email",
    "personal_calendar_list_events",
    "personal_calendar_create_event",
    "personal_calendar_update_event",
    "personal_drive_search_files",
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
    assert (
        servers["datadog"]["url"]
        == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
    )
    assert servers["sentry"]["type"] == "http"
    assert servers["sentry"]["url"] == "https://mcp.sentry.dev/mcp"
    assert servers["bigquery"]["type"] == "stdio"
    assert servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")
    assert servers["bigquery"]["args"] == []
    assert servers["github"]["bearer_token_env_var"] == "GITHUB_PAT"
    assert servers["personal-actions"]["command"].endswith("/bin/personal-actions-mcp")
    assert servers["agent-broker"]["command"].endswith("/bin/agent-broker-mcp")

    profiles_dir = ROOT / "profiles"
    required_profiles = {
        "plan-readonly",
        "code-edit",
        "repo-maintainer",
        "personal-assistant",
        "prod-observer",
        "prod-mutator-confirmed",
    }
    actual_profiles = {path.stem for path in profiles_dir.glob("*.json")}
    assert required_profiles.issubset(actual_profiles)
    for name in required_profiles:
        profile = load_json(profiles_dir / f"{name}.json")
        assert profile["name"] == name
        assert isinstance(profile["mcp_servers"], list)
        assert isinstance(profile["confirm"], list)
        assert profile["risk"] in {"low", "medium", "high", "critical"}

    codex_toml = HOME / ".codex" / "config.toml"
    if codex_toml.exists():
        codex = tomllib.loads(read(codex_toml))
        codex_servers = codex.get("mcp_servers", {})
        assert REQUIRED_MCP.issubset(set(codex_servers)), (
            "Codex config missing required MCP servers"
        )
        assert codex_servers["linear"]["url"] == "https://mcp.linear.app/mcp"
        assert (
            codex_servers["datadog"]["url"]
            == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
        )
        assert codex_servers["sentry"]["url"] == "https://mcp.sentry.dev/mcp"
        assert codex_servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")
        assert codex_servers["bigquery"]["args"] == []
        assert codex.get("features", {}).get("experimental_use_rmcp_client") is True

    claude_json = HOME / ".claude.json"
    if claude_json.exists():
        claude = load_json(claude_json)
        assert isinstance(claude, dict)
        claude_servers = claude.get("mcpServers", {})
        assert REQUIRED_MCP.issubset(set(claude_servers)), (
            "Claude config missing required MCP servers"
        )
        assert claude_servers["linear"]["url"] == "https://mcp.linear.app/mcp"
        assert (
            claude_servers["datadog"]["url"]
            == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
        )
        assert claude_servers["sentry"]["url"] == "https://mcp.sentry.dev/mcp"
        assert claude_servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")

    hermes_config = HOME / ".hermes" / "config.yaml"
    if hermes_config.exists():
        hermes = read(hermes_config)
        assert_contains(hermes, "agents_readonly:", "Hermes config")
        assert_contains(hermes, "personal_actions:", "Hermes config")
        for tool in PERSONAL_ACTION_TOOLS:
            assert_contains(
                hermes, f"- {tool}", "Hermes personal_actions tool allowlist"
            )

    server = read(ROOT / "mcp-servers" / "personal-actions" / "server.py")
    for tool in PERSONAL_ACTION_TOOLS:
        assert re.search(rf"def {re.escape(tool)}\(", server), (
            f"personal-actions server missing {tool}"
        )
    assert "/trash" in server
    assert "/delete" not in server

    broker = read(ROOT / "mcp-servers" / "agent-broker" / "server.py")
    assert_contains(broker, "authorize_tool_call", "agent-broker MCP")

    control = read(ROOT / "scripts" / "agent_control.py")
    for phrase in [
        "cmd_profile",
        "cmd_ledger",
        "cmd_queue",
        "cmd_approve",
        "cmd_eval",
        "broker_authorize",
        "classify_effect",
        "verify_ledger",
        "expire_approvals",
        "compile_claude_settings",
        "broker_hook_decision",
        "compile_sandbox",
        "codex_sandbox_args",
    ]:
        assert_contains(control, phrase, "agent control script")
    # broker enforces the provenance (tainted-context) rule and a fail-closed effect default.
    assert_contains(control, "context_tainted", "broker provenance rule")
    assert_contains(control, "fail closed", "broker fail-closed classification")
    # policy is enforced natively: a PreToolUse hook (not just the advisory MCP) and OS sandbox.
    assert (ROOT / "hooks" / "profile-broker.sh").exists()
    agentp = read(ROOT / "bin" / "agentp")
    assert_contains(
        agentp, "AGENTS_PROFILE", "agentp activates the profile-broker hook"
    )
    assert_contains(agentp, "--codex", "agentp supports native Codex containment")
    syncsrc = read(ROOT / "bin" / "agents-sync")
    assert_contains(
        syncsrc, "profile-broker.sh", "agents-sync wires the PreToolUse broker hook"
    )

    spec = read(ROOT / "specs" / "agent-control-plane.md")
    for phrase in [
        "Permission profiles",
        "Run ledger",
        "Background queue",
        "Approval inbox",
        "MCP broker",
    ]:
        assert_contains(spec, phrase, "agent control spec")

    eval_tasks = {path.stem for path in (ROOT / "evals" / "tasks").glob("*.json")}
    assert {
        "smoke-noop",
        "profile-compile",
        "mcp-contract",
        "prompt-injection-policy",
        "personal-actions-dry-run",
        "dashboard-smoke",
        "queue-smoke",
        "policy-enforcement",
    }.issubset(eval_tasks)
    assert (ROOT / "systemd" / "agentq-worker.service").exists()
    assert (ROOT / "systemd" / "agentq-worker.timer").exists()
    assert (ROOT / "systemd" / "otel-stack.service").exists()
    assert (ROOT / "bin" / "agentp").exists()
    assert (ROOT / "tests" / "behavioral_policy.py").exists()

    policy = read(ROOT / "assistant" / "policy.md")
    assert_contains(policy, "exact Gmail message id", "personal assistant policy")
    assert_contains(
        policy, "permanent Gmail delete endpoint", "personal assistant policy"
    )
    assert_contains(policy, "bulk delete", "personal assistant policy")
    assert_contains(policy, "Datadog MCP", "personal assistant policy")
    assert_contains(policy, "Sentry MCP", "personal assistant policy")
    assert_contains(policy, "read-only", "personal assistant policy")

    oauth_example = read(ROOT / "assistant" / "windmill" / "oauth.env.example")
    for port in ["8765", "8766", "8767", "8768"]:
        assert_contains(
            oauth_example, f"http://127.0.0.1:{port}/callback", "Windmill OAuth example"
        )

    print("agent system contract OK")


if __name__ == "__main__":
    main()
