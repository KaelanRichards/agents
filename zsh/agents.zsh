# agents.zsh — cross-platform shell env (source this from ~/.zshrc).
# Mirrors the laptop dev environment so the remote VM behaves identically.

# Homebrew (Linux or macOS)
for _b in /home/linuxbrew/.linuxbrew/bin/brew /opt/homebrew/bin/brew; do
  [ -x "$_b" ] && eval "$("$_b" shellenv)" && break
done
unset _b

export PATH="$HOME/.local/bin:$PATH"
# mise shims so node/npx/python resolve in non-interactive / agent-spawned shells
[ -d "$HOME/.local/share/mise/shims" ] && export PATH="$HOME/.local/share/mise/shims:$PATH"
command -v mise     >/dev/null && eval "$(mise activate zsh)"
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
command -v starship >/dev/null && eval "$(starship init zsh)"
command -v fzf      >/dev/null && source <(fzf --zsh) 2>/dev/null

# modern ls
if command -v eza >/dev/null; then
  alias ls='eza --group-directories-first'
  alias ll='eza -lah --group-directories-first --git'
  alias la='eza -a'
  alias lt='eza --tree --level=2'
fi

# hands-off agent modes (guard hook + sandbox still apply)
alias yc='claude --permission-mode auto'
alias yx='codex --full-auto'

# jj (Jujutsu) shortcuts
alias j='jj'
alias js='jj st'
alias jl='jj log'
alias jd='jj describe -m'
alias jn='jj new'
alias je='jj edit'
alias jf='jj git fetch'
alias jp='jj git push'
alias jb='jj bookmark'

# Repeated CI/remote runs vs the same repo? Keep the prompt cached for an hour:
# export ENABLE_PROMPT_CACHING_1H=1

# GitHub PAT for the GitHub MCP — set this in the VM's environment/secrets.
# export GITHUB_PAT="..."
