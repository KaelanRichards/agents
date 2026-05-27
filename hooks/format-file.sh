#!/usr/bin/env bash
# Shared PostToolUse formatter for Claude Code + Codex.
# Reads the hook JSON on stdin and formats the edited file(s).
# Best-effort: always exits 0, never blocks the agent.
set -uo pipefail
# Portable PATH: Homebrew prefix differs (macOS vs linuxbrew). Detect at runtime.
for _brew in /opt/homebrew/bin /home/linuxbrew/.linuxbrew/bin /usr/local/bin; do
	[ -d "$_brew" ] && case ":$PATH:" in *":$_brew:"*) ;; *) PATH="$_brew:$PATH" ;; esac
done
unset _brew
PATH="$HOME/.local/share/mise/shims:$HOME/.cargo/bin:$PATH"
export PATH
command -v jq >/dev/null || exit 0
input=$(cat)

format_one() {
	local f="$1"
	[ -f "$f" ] || return 0
	case "$f" in
	*.py) ruff format -- "$f" >/dev/null 2>&1 ;;
	*.js | *.jsx | *.ts | *.tsx | *.mjs | *.cjs | *.json | *.jsonc | *.css | *.scss)
		biome format --write -- "$f" >/dev/null 2>&1
		;;
	*.sh | *.bash) shfmt -w -- "$f" >/dev/null 2>&1 ;;
	*.rs) rustfmt -- "$f" >/dev/null 2>&1 ;;
	esac
}

fp=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [ -n "$fp" ]; then
	format_one "$fp" # Claude: single edited file
elif git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
	# Codex apply_patch / multi-file: format files changed in the working tree
	while IFS= read -r f; do format_one "$f"; done \
		< <(git diff --name-only --diff-filter=ACM 2>/dev/null)
fi
exit 0
