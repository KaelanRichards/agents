#!/usr/bin/env bash
# sync-roundtrip — assert mcp-sync propagates a server to BOTH Claude (JSON) and Codex (TOML),
# and that removal cleans both. Needs the live config (run after bootstrap). Self-cleaning.
set -uo pipefail
name="_roundtrip_$$"
cleanup() { mcp-sync remove "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
fail=0

mcp-sync add "$name" -- echo hello >/dev/null
jq -e --arg n "$name" '.mcpServers[$n]' "$HOME/.claude.json" >/dev/null 2>&1 && echo "add  -> claude: ok" || {
	echo "add  -> claude: MISSING"
	fail=1
}
grep -qF "[mcp_servers.$name]" "$HOME/.codex/config.toml" && echo "add  -> codex: ok" || {
	echo "add  -> codex: MISSING"
	fail=1
}

mcp-sync remove "$name" >/dev/null
jq -e --arg n "$name" '.mcpServers[$n]' "$HOME/.claude.json" >/dev/null 2>&1 && {
	echo "rm   -> claude: STILL PRESENT"
	fail=1
} || echo "rm   -> claude: ok"
grep -qF "[mcp_servers.$name]" "$HOME/.codex/config.toml" && {
	echo "rm   -> codex: STILL PRESENT"
	fail=1
} || echo "rm   -> codex: ok"

[ "$fail" -eq 0 ] && echo "sync round-trip OK" || echo "sync round-trip FAILED"
exit "$fail"
