#!/usr/bin/env bash
# sync-roundtrip — assert mcp-sync propagates a server to BOTH Claude (JSON) and
# Codex (TOML), and that removal cleans both. Uses an isolated HOME so the test
# never mutates live agent config.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
cleanup() { rm -rf -- "${tmp:?}"; }
trap cleanup EXIT

export HOME="$tmp/home"
export AGENTS_HOME="$tmp/agents"
export PATH="$repo/bin:$PATH"
mkdir -p "$HOME/.codex" "$HOME/.claude" "$AGENTS_HOME"
printf '{"mcpServers":{}}\n' >"$AGENTS_HOME/mcp.json"

name="_roundtrip_$$"

# Check a Codex server key by parsing the TOML, not by grepping a quoted/bare spelling.
# Avoid python3 here: under the isolated HOME it resolves through mise without the real trust store.
codex_has() { yq -p toml -o json "$HOME/.codex/config.toml" | jq -e --arg n "$1" '.mcp_servers[$n]' >/dev/null; }

mcp-sync add "$name" -- echo hello >/dev/null
jq -e --arg n "$name" '.mcpServers[$n]' "$HOME/.claude.json" >/dev/null
codex_has "$name"
echo "add  -> claude: ok"
echo "add  -> codex: ok"

mcp-sync remove "$name" >/dev/null
if jq -e --arg n "$name" '.mcpServers[$n]' "$HOME/.claude.json" >/dev/null 2>&1; then
	echo "rm   -> claude: STILL PRESENT"
	exit 1
fi
if codex_has "$name"; then
	echo "rm   -> codex: STILL PRESENT"
	exit 1
fi
echo "rm   -> claude: ok"
echo "rm   -> codex: ok"

# A full client override replaces the shared transport; a partial one keeps it. Host overlays
# merge recursively and replace arrays, so they can adjust one client without restating a server.
cat >"$AGENTS_HOME/mcp.json" <<'JSON'
{
  "mcpServers": {
    "_transport": {
      "type": "stdio",
      "command": "$AGENTS_HOME/bin/shared",
      "args": ["shared", "not-real-argument-secret"],
      "env": {"FIXTURE_SECRET": "not-real-env-secret"},
      "startup_timeout_sec": 60,
      "clients": {
        "codex": {
          "type": "http",
          "url": "https://example.invalid/mcp",
          "auth": "oauth",
          "required": true,
          "enabled_tools": ["read"],
          "disabled_tools": ["write"],
          "default_tools_approval_mode": "writes",
          "tools": {"read": {"approval_mode": "auto"}}
        }
      }
    },
    "_disabled": {
      "type": "stdio",
      "command": "echo",
      "args": ["base"],
      "cwd": "/tmp",
      "env_vars": ["FORWARDED_ENV"],
      "experimental_environment": "remote",
      "clients": {
        "codex": {"enabled": false}
      }
    }
  }
}
JSON
cat >"$AGENTS_HOME/mcp.local.json" <<'JSON'
{
  "mcpServers": {
    "_transport": {
      "clients": {
        "codex": {"url": "https://host.example.invalid/mcp"}
      }
    },
    "_disabled": {"args": ["overlay"]}
  }
}
JSON
# Add fake credential-shaped values to the overlay. Sync must preserve them in generated config,
# while `mcp-sync check` must expose only names/counts and never their values.
overlay_tmp=$(mktemp)
jq '.mcpServers._transport.clients.codex += {
  url: "https://host.example.invalid/mcp?token=not-real-query-secret",
  headers: {Authorization: "not-real-header-secret"},
  env_http_headers: {"X-Token": "HEADER_TOKEN_ENV"}
}' "$AGENTS_HOME/mcp.local.json" >"$overlay_tmp"
mv "$overlay_tmp" "$AGENTS_HOME/mcp.local.json"
mcp-sync >/dev/null

codex_json="$(yq -p toml -o json "$HOME/.codex/config.toml")"
jq -e '.mcpServers._transport.command | endswith("/agents/bin/shared")' "$HOME/.claude.json" >/dev/null
jq -e '.mcpServers._transport.args == ["shared", "not-real-argument-secret"]' "$HOME/.claude.json" >/dev/null
jq -e '.mcpServers._disabled.args == ["overlay"]' "$HOME/.claude.json" >/dev/null
jq -e '.mcpServers._disabled | has("enabled") | not' "$HOME/.claude.json" >/dev/null
jq -e '.mcpServers[] | has("clients") | not' "$HOME/.claude.json" >/dev/null
jq -e '.mcpServers[] | has("startup_timeout_sec") | not' "$HOME/.claude.json" >/dev/null
jq -e 'all(.mcpServers[]; (has("required") or has("enabled_tools") or has("env_vars") or has("experimental_environment")) | not)' "$HOME/.claude.json" >/dev/null
jq -e '.mcp_servers._transport.url == "https://host.example.invalid/mcp?token=not-real-query-secret"' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._transport | has("command") | not' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._transport.auth == "oauth" and .mcp_servers._transport.required == true' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._transport.enabled_tools == ["read"] and .mcp_servers._transport.disabled_tools == ["write"]' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._transport.default_tools_approval_mode == "writes" and .mcp_servers._transport.tools.read.approval_mode == "auto"' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._transport.http_headers.Authorization == "not-real-header-secret" and .mcp_servers._transport.env_http_headers["X-Token"] == "HEADER_TOKEN_ENV"' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._disabled.args == ["overlay"]' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._disabled.enabled == false' <<<"$codex_json" >/dev/null
jq -e '.mcp_servers._disabled.cwd == "/tmp" and .mcp_servers._disabled.env_vars == ["FORWARDED_ENV"] and .mcp_servers._disabled.experimental_environment == "remote"' <<<"$codex_json" >/dev/null

check_output=$(mcp-sync check)
for secret in not-real-argument-secret not-real-env-secret not-real-query-secret not-real-header-secret; do
	if [[ "$check_output" == *"$secret"* ]]; then
		echo "check -> leaked fixture secret: $secret"
		exit 1
	fi
done
[[ "$check_output" == *"?<redacted-query>"* ]]
echo "check redaction: ok"
echo "client overrides + overlay merge: ok"
echo "sync round-trip OK"
