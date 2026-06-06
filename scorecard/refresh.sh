#!/bin/zsh
# Weekly refresh of the "Engineering Scorecard (CTO)" Notion page.
# Runs headless via launchd (com.vizcom.scorecard-refresh). Reuses local MCP auth
# (~/.mcp-auth for Datadog/Sentry/Notion, gh token for GitHub).
#
# Run manually any time:  ~/.config/agents/scorecard/refresh.sh
set -uo pipefail

DIR="$HOME/.config/agents/scorecard"
LOG="$DIR/logs/refresh-$(date +%Y%m%d-%H%M%S).log"

# launchd starts with a minimal environment — set PATH for claude/node/gh/mise.
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.orbstack/bin"

# Least-privilege allowlist: every read tool needed, plus exactly ONE write
# (notion-update-page). No --permission-mode bypass: in headless `-p` mode any tool
# NOT on this list is auto-denied, so approval gates stay intact and the bash guard
# hook still blocks destructive commands.
ALLOWED=(
	"Bash(gh:*)" "Bash(date:*)"
	mcp__datadog__aggregate_spans mcp__datadog__get_datadog_metric
	mcp__datadog__search_datadog_monitors mcp__datadog__search_datadog_metrics
	mcp__datadog__list_datadog_skills mcp__datadog__load_datadog_skill
	mcp__sentry__whoami mcp__sentry__find_organizations mcp__sentry__find_projects
	mcp__sentry__find_releases mcp__sentry__search_events mcp__sentry__search_issues
	mcp__notion__notion-fetch mcp__notion__notion-search mcp__notion__notion-update-page
)

{
	echo "=== scorecard refresh $(date) ==="
	command -v claude || {
		echo "claude not found on PATH"
		exit 127
	}

	claude -p "$(cat "$DIR/refresh-prompt.md")" \
		--allowedTools "${ALLOWED[@]}" \
		--model claude-sonnet-4-6

	echo "=== exit $? at $(date) ==="
} >>"$LOG" 2>&1

# keep only the 12 most recent logs
ls -1t "$DIR"/logs/refresh-*.log 2>/dev/null | tail -n +13 | xargs rm -f 2>/dev/null
