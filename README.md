# agents — portable agent environment (laptop + always-on VM)

Single source of truth for Claude Code + Codex CLI: instructions (`AGENTS.md`), MCP servers
(`mcp.json`), subagents/skills/hooks, helper scripts (`bin/`), shell env (`zsh/agents.zsh`),
and a `bootstrap.sh` that reproduces the whole thing on a fresh Linux box.

## Run it on an always-on VM (so you can close your laptop)

1. **Provision a small Linux VM** — Ubuntu 24.04, ≥ 2 GB RAM (e.g. Hetzner CPX21,
   DigitalOcean, Fly Machines). Add your SSH key.
2. **Bootstrap** (on the VM):
   ```bash
   git clone <this-repo-url> ~/.config/agents
   bash ~/.config/agents/bootstrap.sh
   exec zsh
   ```
3. **Authenticate**: `claude` → `/login`, `codex login`, `gh auth login`, and set
   `GITHUB_PAT` (for the GitHub MCP).

## Daily workflow

```bash
ssh you@vm           # or: mosh you@vm   (survives flaky networks)
tmux new -s work     # or: zellij        (persistent session)
yc                   # Claude, hands-off   (or: claude)
# ...work...
# detach: Ctrl-b d   → close your laptop. The VM keeps running.
# later, from anywhere:
mosh you@vm
tmux attach -t work  # everything is exactly where you left it
```

**From your phone:** a terminal app (Blink / Termius) over SSH/Mosh, or Claude Code's
`/remote-control` / `claude.ai/code`.

## Keep laptop and VM in sync

This dir is a colocated jj repo. After changing config:
```bash
cd ~/.config/agents
jj describe -m "update config"; jj bookmark set main -r @; jj git push
# on the VM:
cd ~/.config/agents && jj git fetch && jj rebase -d main@origin
mcp-sync && agents-sync     # regenerate Claude + Codex configs
```

## Notes
- Secrets are **never** committed — only `bearer_token_env_var` *names* live in `mcp.json`.
- The guard hook is active here too; destructive commands stay blocked.
- Tools: see `Brewfile`. Languages via `mise` + `rustup`. VCS is jj-first (colocated).
