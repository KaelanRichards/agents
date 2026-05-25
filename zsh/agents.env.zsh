# agents.env.zsh — env + PATH for EVERY zsh: interactive, login, AND the non-interactive
# shells that agents (Claude Code / Codex) spawn for their Bash tool. Source from ~/.zshenv.
#
# Keep this fast and side-effect-free: PATH/env only. Prompt, completions, and aliases are
# interactive concerns and live in agents.zsh (sourced from ~/.zshrc) instead.
#
# Why this file exists: zsh reads ~/.zshenv for every shell, but ~/.zprofile/~/.zshrc only for
# login/interactive ones. Putting the toolchain here is what makes `node`/`brew`/`rg`/`docker`
# resolve in agent-spawned shells — without it, agents must prefix every command with
# `eval "$(brew shellenv)"`.
#
# Idempotent by construction (re-prepends only when missing); NO exported sentinel — an
# exported guard leaks into child shells and would suppress setup before PATH is built.

# prepend a dir to PATH only if it exists and isn't already there (no duplicates)
_agents_path_prepend() { case ":${PATH}:" in *":$1:"*) ;; *) [ -d "$1" ] && PATH="$1:${PATH}" ;; esac; }

# Homebrew (macOS Apple Silicon or Linuxbrew) — skip the (slowish) eval if already on PATH
if ! command -v brew >/dev/null 2>&1; then
  for _b in /opt/homebrew/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    [ -x "$_b" ] && eval "$("$_b" shellenv)" && break
  done
  unset _b
fi

_agents_path_prepend "$HOME/.local/bin"                    # agent helper scripts
_agents_path_prepend "$HOME/.local/share/mise/shims"       # node/pnpm/python (+ per-repo versions)
_agents_path_prepend "$HOME/.orbstack/bin"                 # OrbStack docker CLI (macOS)
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"          # rustup / cargo

export PATH
unset -f _agents_path_prepend 2>/dev/null
