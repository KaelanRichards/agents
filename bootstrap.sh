#!/usr/bin/env bash
# bootstrap.sh — reproduce the full agent setup on a fresh Linux VM (Ubuntu/Debian).
#
# On the VM:
#   git clone <repo-url> ~/.config/agents
#   bash ~/.config/agents/bootstrap.sh
set -euo pipefail
AH="$HOME/.config/agents"

echo "==> base packages"
if command -v apt-get >/dev/null 2>&1; then
	sudo apt-get update -y
	sudo apt-get install -y build-essential procps curl file git zsh tmux
fi

echo "==> Homebrew (Linux)"
if ! command -v brew >/dev/null 2>&1; then
	NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
BREW="$(command -v brew || echo /home/linuxbrew/.linuxbrew/bin/brew)"
eval "$("$BREW" shellenv)"

echo "==> CLI toolbelt (brew bundle)"
brew bundle --file="$AH/Brewfile"

echo "==> languages: mise (node/pnpm/python) + rust"
# Pin major versions so a fresh bootstrap a year from now produces a reproducible toolchain.
# Bump these intentionally and verify with `agents-doctor` + the smoke tests.
mise use -g node@lts pnpm@9 python@3.12
# auto-read per-repo .nvmrc / .node-version / .python-version on cd
mise settings set idiomatic_version_file_enable_tools "node,python" 2>/dev/null || true
[ -f "$HOME/.cargo/env" ] || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path

echo "==> agent CLIs (claude + codex)"
command -v codex >/dev/null 2>&1 || brew install codex || npm install -g @openai/codex || true
command -v claude >/dev/null 2>&1 || curl -fsSL https://claude.ai/install.sh | bash || npm install -g @anthropic-ai/claude-code || true

echo "==> link helper scripts + project dir"
mkdir -p "$HOME/.local/bin" "$HOME/code"
for s in "$AH"/bin/*; do
	chmod +x "$s"
	dest="$HOME/.local/bin/$(basename "$s")"
	# Don't silently shadow an unrelated tool with the same name. Only overwrite
	# if the destination is missing or already points back at our bin/.
	if [ -e "$dest" ] && [ ! -L "$dest" ]; then
		echo "    skip: $dest exists and is not a symlink (refusing to shadow)"
		continue
	fi
	if [ -L "$dest" ]; then
		current=$(readlink "$dest" || true)
		case "$current" in
		"$AH"/bin/*) ;;
		*)
			echo "    skip: $dest -> $current (not ours)"
			continue
			;;
		esac
	fi
	ln -sfn "$s" "$dest"
done

echo "==> instruction symlinks (AGENTS.md is the source of truth)"
mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.config/jj"
ln -sf "$AH/AGENTS.md" "$HOME/.claude/CLAUDE.md"
ln -sf "$AH/AGENTS.md" "$HOME/.codex/AGENTS.md"
# Symlink (not copy) jj config so edits to the canonical file take effect immediately —
# matches how every other dotfile here is wired.
ln -sf "$AH/jj/config.toml" "$HOME/.config/jj/config.toml"
mkdir -p "$HOME/.config/tmux"
ln -sf "$AH/tmux/tmux.conf" "$HOME/.config/tmux/tmux.conf"

echo "==> zsh (env for ALL shells via ~/.zshenv; interactive via ~/.zshrc)"
# ~/.zshenv is read by every zsh incl. non-interactive agent shells -> toolchain on PATH
[ -f "$HOME/.zshenv" ] || touch "$HOME/.zshenv"
grep -q 'agents/zsh/agents.env.zsh' "$HOME/.zshenv" ||
	echo '[ -f "$HOME/.config/agents/zsh/agents.env.zsh" ] && . "$HOME/.config/agents/zsh/agents.env.zsh"' >>"$HOME/.zshenv"
[ -f "$HOME/.zshrc" ] || touch "$HOME/.zshrc"
grep -q 'agents/zsh/agents.zsh' "$HOME/.zshrc" ||
	echo '[ -f "$HOME/.config/agents/zsh/agents.zsh" ] && source "$HOME/.config/agents/zsh/agents.zsh"' >>"$HOME/.zshrc"

echo "==> sync MCP servers + subagents/skills/hooks"
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:$PATH"
mcp-sync
agents-sync

cat <<'NEXT'

✓ bootstrap complete. Remaining manual steps:
  1. Authenticate:   claude  (then /login)  ·  codex login  ·  gh auth login
  2. Secret:         export GITHUB_PAT=...   (add to ~/.zshrc or a secrets manager)
  3. Default shell:  chsh -s "$(command -v zsh)"
  4. Work in a persistent session so it survives disconnect / a closed laptop:
       tmux new -s work
       # detach: Ctrl-b d      reattach: tmux attach -t work
NEXT
