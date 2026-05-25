# agents.zsh — interactive shell setup (prompt, completions, aliases). Source from ~/.zshrc.
#
# Env/PATH (brew, ~/.local/bin, mise shims, cargo, OrbStack) lives in agents.env.zsh and is
# loaded for ALL shells via ~/.zshenv. We source it here too (idempotent) so this file still
# works if ~/.zshenv isn't wired yet.
[ -f "$HOME/.config/agents/zsh/agents.env.zsh" ] && . "$HOME/.config/agents/zsh/agents.env.zsh"

# mise: interactive activation adds a precmd hook for auto version-switching on `cd`
# (non-interactive shells rely on the shims from agents.env.zsh instead).
command -v mise     >/dev/null && eval "$(mise activate zsh)"
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
# GitHub PAT for the GitHub MCP — set this in the VM's environment/secrets:
# export GITHUB_PAT="..."
