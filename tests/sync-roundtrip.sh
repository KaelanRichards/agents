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
printf '{"mcpServers":{}}\n' > "$AGENTS_HOME/mcp.json"

name="_roundtrip_$$"

mcp-sync add "$name" -- echo hello >/dev/null
jq -e --arg n "$name" '.mcpServers[$n]' "$HOME/.claude.json" >/dev/null
grep -qF "[mcp_servers.$name]" "$HOME/.codex/config.toml"
echo "add  -> claude: ok"
echo "add  -> codex: ok"

mcp-sync remove "$name" >/dev/null
if jq -e --arg n "$name" '.mcpServers[$n]' "$HOME/.claude.json" >/dev/null 2>&1; then
	echo "rm   -> claude: STILL PRESENT"
	exit 1
fi
if grep -qF "[mcp_servers.$name]" "$HOME/.codex/config.toml"; then
	echo "rm   -> codex: STILL PRESENT"
	exit 1
fi
echo "rm   -> claude: ok"
echo "rm   -> codex: ok"
echo "sync round-trip OK"
