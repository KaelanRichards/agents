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
    "slack",
    "notion",
    "granola",
    "cloudflare",
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

MCP_REMOTE_BRIDGES = {
    "notion": ("https://mcp.notion.com/mcp", "3334"),
    "granola": ("https://mcp.granola.ai/mcp", "3335"),
    "linear": ("https://mcp.linear.app/mcp", "3336"),
    "sentry": ("https://mcp.sentry.dev/mcp", "3337"),
    "cloudflare": ("https://mcp.cloudflare.com/mcp", "3338"),
}

MCP_REMOTE_WRAPPERS = {
    "slack": "$AGENTS_HOME/bin/slack-official-mcp",
}

PINNED_MCP_REMOTE = "mcp-remote@0.1.38"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: pathlib.Path) -> object:
    return json.loads(read(path))


def assert_contains(text: str, needle: str, label: str) -> None:
    assert needle in text, f"{label} missing {needle!r}"


def assert_mcp_remote_bridge(server: dict, name: str) -> None:
    url, port = MCP_REMOTE_BRIDGES[name]
    assert server.get("type", "stdio") == "stdio"
    assert server["command"] == "npx"
    args = server["args"]
    # mcp-remote must be PINNED (never @latest — it re-resolves every launch and breaks ~/.mcp-auth
    # lockfile coordination, causing slow starts + duplicate OAuth prompts). Version-agnostic so the
    # pin can bump in mcp.json without editing this test.
    assert args[0] == "-y"
    assert args[1].startswith("mcp-remote@") and args[1] != "mcp-remote@latest", (
        f"{name}: mcp-remote must be pinned, got {args[1]!r}"
    )
    assert args[2:] == [url, port, "--host", "127.0.0.1"]


def main() -> None:
    mcp = load_json(ROOT / "mcp.json")
    assert isinstance(mcp, dict)
    servers = mcp.get("mcpServers")
    assert isinstance(servers, dict)
    assert set(servers) == REQUIRED_MCP

    auth = load_json(ROOT / "mcp.auth.json")
    assert auth["policy"]["token_copying"] == "forbidden-by-default"
    auth_servers = auth["servers"]
    assert set(auth_servers) == set(MCP_REMOTE_BRIDGES) | set(MCP_REMOTE_WRAPPERS) | {
        "datadog"
    }
    assert (
        auth_servers["datadog"]["url"]
        == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
    )
    assert auth_servers["datadog"]["strategy"] == "client-native-http-oauth"
    assert auth_servers["datadog"]["login_command"] == "codex mcp login datadog"
    assert (
        auth_servers["datadog"]["clients"]["codex"]["support"]
        == "supported-via-client-native-http-oauth"
    )
    for name, (url, _port) in MCP_REMOTE_BRIDGES.items():
        assert auth_servers[name]["url"] == url
        assert auth_servers[name]["strategy"] == "mcp-remote-stdio"
        assert auth_servers[name]["token_store"] == "~/.mcp-auth"
        assert auth_servers[name]["callback_host"] == "127.0.0.1"
        assert (
            auth_servers[name]["clients"]["claude"]["support"]
            == "supported-via-stdio-bridge"
        )
        assert (
            auth_servers[name]["clients"]["opencode"]["support"]
            == "supported-via-stdio-bridge"
        )
        assert (
            auth_servers[name]["clients"]["codex"]["support"]
            == "supported-via-stdio-bridge"
        )
    for name, command in MCP_REMOTE_WRAPPERS.items():
        assert auth_servers[name]["url"] == "https://mcp.slack.com/mcp"
        assert auth_servers[name]["strategy"] == "mcp-remote-wrapper"
        assert auth_servers[name]["command"] == command
        assert auth_servers[name]["token_store"] == "~/.mcp-auth"
        assert auth_servers[name]["callback_host"] == "127.0.0.1"
        assert (
            auth_servers[name]["clients"]["claude"]["support"]
            == "supported-via-stdio-bridge"
        )
        assert (
            auth_servers[name]["clients"]["opencode"]["support"]
            == "supported-via-stdio-bridge"
        )
        assert (
            auth_servers[name]["clients"]["codex"]["support"]
            == "supported-via-stdio-bridge"
        )

    assert servers["datadog"]["type"] == "http"
    assert (
        servers["datadog"]["url"]
        == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
    )
    assert "headers" not in servers["datadog"]
    assert "bearer_token_env_var" not in servers["datadog"]
    for name in MCP_REMOTE_BRIDGES:
        assert_mcp_remote_bridge(servers[name], name)
    for name, command in MCP_REMOTE_WRAPPERS.items():
        assert servers[name]["type"] == "stdio"
        assert servers[name]["command"] == command
        assert servers[name]["args"] == []
        assert servers[name].get("startup_timeout_sec", 0) >= 60
    assert servers["slack-dm"].get("startup_timeout_sec", 0) >= 60
    assert servers["bigquery"]["type"] == "stdio"
    assert servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")
    assert servers["bigquery"]["args"] == []
    assert servers["github"]["bearer_token_env_var"] == "GITHUB_PAT"
    assert servers["personal-actions"]["command"].endswith("/bin/personal-actions-mcp")
    assert servers["agent-broker"]["command"].endswith("/bin/agent-broker-mcp")
    assert (ROOT / "bin" / "mcp-auth").exists()
    assert (ROOT / "scripts" / "mcp_auth.py").exists()
    slack_wrapper = read(ROOT / "bin" / "slack-official-mcp")
    assert PINNED_MCP_REMOTE in slack_wrapper
    assert "mcp-remote@latest" not in slack_wrapper

    profiles_dir = ROOT / "profiles"
    required_profiles = {
        "plan-readonly",
        "code-edit",
        "repo-maintainer",
        "personal-assistant",
        "prod-observer",
        "prod-mutator-confirmed",
        "vizcom-sre",
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
        assert (
            codex_servers["datadog"]["url"]
            == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
        )
        assert "http_headers" not in codex_servers["datadog"]
        assert "bearer_token_env_var" not in codex_servers["datadog"]
        for name in MCP_REMOTE_BRIDGES:
            assert_mcp_remote_bridge(codex_servers[name], name)
        assert codex_servers["slack"]["command"].endswith("/bin/slack-official-mcp")
        # yq omits an empty args array in TOML; Codex treats a missing args as [] (standard for
        # arg-less stdio servers), so accept either form.
        assert codex_servers["slack"].get("args", []) == []
        assert codex_servers["slack"]["startup_timeout_sec"] >= 60
        assert codex_servers["slack-dm"]["startup_timeout_sec"] >= 60
        assert codex_servers["bigquery"]["command"].endswith("/bin/bigquery-mcp")
        assert codex_servers["bigquery"].get("args", []) == []
        assert codex.get("features", {}).get("experimental_use_rmcp_client") is True

    claude_json = HOME / ".claude.json"
    if claude_json.exists():
        claude = load_json(claude_json)
        assert isinstance(claude, dict)
        claude_servers = claude.get("mcpServers", {})
        assert REQUIRED_MCP.issubset(set(claude_servers)), (
            "Claude config missing required MCP servers"
        )
        assert (
            claude_servers["datadog"]["url"]
            == "https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery"
        )
        assert "headers" not in claude_servers["datadog"]
        for name in MCP_REMOTE_BRIDGES:
            assert_mcp_remote_bridge(claude_servers[name], name)
        assert claude_servers["slack"]["command"].endswith("/bin/slack-official-mcp")
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
        "queue-smoke",
        "policy-enforcement",
        "enforcement-e2e",
    }.issubset(eval_tasks)
    assert (ROOT / "systemd" / "agentq-worker.service").exists()
    assert (ROOT / "systemd" / "agentq-worker.timer").exists()
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
