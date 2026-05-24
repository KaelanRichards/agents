# agents — portable agent environment (laptop + always-on VM)

Single source of truth for Claude Code + Codex CLI: instructions (`AGENTS.md`), MCP servers
(`mcp.json`), subagents/skills/hooks, helper scripts (`bin/`), shell env (`zsh/agents.zsh`),
and a `bootstrap.sh` that reproduces the whole thing on a fresh Linux box.

## Run it on an always-on VM (so you can close your laptop)

**Option A — one command (Hetzner):**
```bash
brew install hcloud
export HCLOUD_TOKEN=...                 # console.hetzner.cloud -> API Tokens
bash ~/.config/agents/provision.sh     # creates the VM and bootstraps it
```
Tunables at the top of `provision.sh`: `VM_TYPE`, `VM_LOCATION`, `VM_USER`, `AGENTS_REPO`
(US / x86: `VM_TYPE=cpx21 VM_LOCATION=ash`).

**Option B — any provider, by hand:**
1. Provision Ubuntu 24.04, ≥ 2 GB RAM (Hetzner / DigitalOcean / Fly); add your SSH key.
2. On the VM: `git clone <repo-url> ~/.config/agents && bash ~/.config/agents/bootstrap.sh`

**Then authenticate** on the VM: `claude` → `/login`, `codex login`, `gh auth login`,
and set `GITHUB_PAT` (GitHub MCP).

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

## Teardown (stop billing)

```bash
bash ~/.config/agents/teardown.sh                # snapshot, then delete (confirms)
bash ~/.config/agents/teardown.sh --no-snapshot -y   # full delete, no prompt
```

## Reproducible env (Nix, optional)

A hermetic, pinned alternative to the brew toolbelt — additive, doesn't replace `bootstrap.sh`.
On a Nix-enabled machine:
```bash
nix develop ~/.config/agents        # ad-hoc shell with the pinned toolbelt
# or, with direnv:  cd ~/.config/agents && direnv allow
```
`flake.nix` pins every CLI tool via nixpkgs (the generated `flake.lock` records the exact
revision). Languages stay mise/uv-managed; `claude`/`codex` install separately (not in nixpkgs).

## Notes
- Secrets are **never** committed — only `bearer_token_env_var` *names* live in `mcp.json`.
- The guard hook is active here too; destructive commands stay blocked.
- Tools: see `Brewfile`. Languages via `mise` + `rustup`. VCS is jj-first (colocated).
