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
mise use -g node@lts pnpm@latest python@3.12
[ -f "$HOME/.cargo/env" ] || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path

echo "==> agent CLIs (claude + codex)"
command -v codex >/dev/null 2>&1 || brew install codex || npm install -g @openai/codex || true
command -v claude >/dev/null 2>&1 || curl -fsSL https://claude.ai/install.sh | bash || npm install -g @anthropic-ai/claude-code || true

echo "==> optional Nix (set BOOTSTRAP_NIX=1 for the reproducible flake toolbelt)"
if [ "${BOOTSTRAP_NIX:-0}" = "1" ]; then
	if ! command -v nix >/dev/null 2>&1; then
		curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix -o /tmp/nix-installer.sh
		sh /tmp/nix-installer.sh install --no-confirm
	fi
	echo "    Nix ready — pinned toolbelt:  nix develop ~/.config/agents"
fi

echo "==> link helper scripts + project dir"
mkdir -p "$HOME/.local/bin" "$HOME/code"
for s in "$AH"/bin/*; do
	chmod +x "$s"
	ln -sf "$s" "$HOME/.local/bin/$(basename "$s")"
done

echo "==> instruction symlinks (AGENTS.md is the source of truth)"
mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.config/jj"
ln -sf "$AH/AGENTS.md" "$HOME/.claude/CLAUDE.md"
ln -sf "$AH/AGENTS.md" "$HOME/.codex/AGENTS.md"
cp -f "$AH/jj/config.toml" "$HOME/.config/jj/config.toml"
mkdir -p "$HOME/.config/tmux" "$HOME/.config/zellij"
ln -sf "$AH/tmux/tmux.conf" "$HOME/.config/tmux/tmux.conf"
ln -sf "$AH/zellij/config.kdl" "$HOME/.config/zellij/config.kdl"

echo "==> zsh"
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
       tmux new -s work        # or: zellij
       # detach: Ctrl-b d      reattach: tmux attach -t work
NEXT
