#!/usr/bin/env bash
# profile-broker.sh — Claude PreToolUse hook that ENFORCES the active agentp profile on MCP tool
# calls. This is the load-bearing counterpart to the advisory `authorize_tool_call` tool on the
# agents MCP: a PreToolUse hook runs before the model sees the result and cannot be routed around.
#
# No-op unless AGENTS_PROFILE is set (i.e. the session was launched via `agentp <profile>`) and the
# pending tool is an MCP tool. Reuses broker_authorize() so policy lives in exactly one place.
set -euo pipefail
prof="${AGENTS_PROFILE:-}"
[ -n "$prof" ] || exit 0
input="$(cat)"
# Fast path: only pay the Python startup for MCP tool calls under an active profile.
tool="$(printf '%s' "$input" | jq -r '.tool_name // ""' 2>/dev/null || echo "")"
case "$tool" in
mcp__*) ;;
*) exit 0 ;;
esac
AH="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s' "$input" | python3 "$AH/scripts/agent_control.py" broker-hook --profile "$prof"
