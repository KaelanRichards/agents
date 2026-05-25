# agents — portable agent environment (laptop + always-on VM)

Single source of truth for **Claude Code + Codex CLI**: instructions (`AGENTS.md`), MCP servers
(`mcp.json`), subagents/skills/hooks, helper scripts (`bin/`), shell env (`zsh/agents.env.zsh`
for all shells plus `zsh/agents.zsh` for interactive extras), dashboards, observability, CI,
and a `bootstrap.sh` that reproduces the whole thing on a fresh box.

## Provision an always-on VM (so you can close your laptop)

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
and set `GITHUB_PAT` (GitHub MCP). Run `agents-doctor` to confirm it's healthy.

## Daily workflow

```bash
mosh you@vm          # or ssh (mosh survives flaky networks)
tmux new -s work     # or: zellij        (persistent session)
yc                   # Claude, hands-off   (yx for Codex; or plain claude/codex)
# ...work...
# detach: Ctrl-b d   → close your laptop. The VM keeps running.
mosh you@vm; tmux attach -t work   # later, from anywhere — exactly where you left it
```
**From your phone:** a terminal app (Blink / Termius) over SSH/Mosh, **or** the web dashboard
at `https://<vm>.<tailnet>.ts.net` (see below), or Claude Code's `/remote-control`.

## Dashboards & control

Three views over the same data (machines+cost, health, MCP, CI/PRs, sessions) — pick by context:
- **`agents-status`** — one-shot text overview.
- **`dash`** — live TUI control center (panels + keys: `r` refresh · `s` sync · `d` doctor · `g` grafana · `q` quit).
- **`dashweb`** — live HTML control center: SSE cards, streamed action logs, control buttons
  (sync/doctor/provision/teardown/reboot, MCP add/remove), embedded Grafana + terminal.

```bash
dashweb     # local: http://localhost:8787 (no token — localhost-only)
```
Panel prerequisites: Grafana panel needs `obs up`; terminal panel needs `ttyd -p 7681 -W zsh`.

### Always-on + phone access (on the VM)
```bash
serve       # on the VM: installs the webdash systemd service (always-on) + tailscale serve
```
Runs webdash 24/7 (systemd, `Restart=always`, linger) behind **`tailscale serve`** at
`https://<vm>.<tailnet>.ts.net` — tailnet-only HTTPS, webdash stays localhost-bound. A
`WEBDASH_TOKEN` (in the VM's `webdash.env`) gates it as defense-in-depth: first visit with
`?token=<token>` sets a 30-day cookie, then the bare URL works. Requires Tailscale "Serve"
enabled on the tailnet + `tailscale up` on the VM and your devices.

## Keep laptop and VM in sync

The **laptop** repo is a colocated jj repo; the **VM** is a plain git clone.
```bash
# laptop — commit & push (jj):
jj -R ~/.config/agents describe -m "update config"
jj -R ~/.config/agents bookmark set main -r @ && jj -R ~/.config/agents git push
# VM — pull & regenerate (run on the VM):
git -C ~/.config/agents pull && mcp-sync && agents-sync
systemctl --user restart webdash.service    # if the dashboard changed
```

## Reproducible env (Nix, optional)

A hermetic, pinned alternative to the brew toolbelt — additive, doesn't replace `bootstrap.sh`.
```bash
nix develop ~/.config/agents        # ad-hoc shell with the pinned toolbelt
# or, with direnv:  cd ~/.config/agents && direnv allow
```
`flake.nix` pins every CLI tool via nixpkgs (`flake.lock` records the exact revision). Languages
stay mise/uv-managed; `claude`/`codex` install separately. On the VM,
`BOOTSTRAP_NIX=1 bash ~/.config/agents/bootstrap.sh` installs Nix alongside brew.

## Teardown (stop billing)

```bash
bash ~/.config/agents/teardown.sh                # snapshot, then delete (confirms)
bash ~/.config/agents/teardown.sh --no-snapshot -y   # full delete, no prompt
```

## Maintenance & health
- **`agents-doctor`** — verify tools, symlinks, MCP parity, configs, and agent-CLI version drift
  (run anytime, or on a new machine).
- **`just ci-local`** — local verification loop: shell scripts, JSON locks, sync round-trip,
  dashboard smoke test, `gitleaks`, and `agents-doctor`.
- **`skills-audit` / `skills-update`** — review vendored skill provenance and executable surface,
  then report upstream drift without modifying files. `skills.lock.json` is the source of truth.
- **`mcp-update`** — report npm drift for pinned stdio MCP packages without modifying `mcp.json`.
- **`hermes-sync`** — generate the managed Hermes personal-assistant profile at
  `~/.hermes/config.yaml`. Hermes uses the shared local `personal-actions-mcp` facade for Slack,
  Gmail, and Calendar writes plus read-only `agents` MCP tools.
- **`obs up`** — local OpenTelemetry → Prometheus → Grafana stack for agent cost/usage
  (`obs env` prints the env that streams Claude Code telemetry to it).
- **CI** (`.github/workflows/ci.yml`): lints + validates on every push; weekly it runs the
  bootstrap smoke test, `agents-doctor`, the sync round-trip test, and `nix flake check`.
- **Auto-updates:** Dependabot (Actions) + the `update-flake` workflow open CI-validated PRs.

## Notes
- Secrets are **never** committed — only `bearer_token_env_var` *names* live in `mcp.json`;
  tokens live in the macOS keychain (laptop) or `webdash.env` (VM).
- MCP stdio package versions are pinned in `mcp.json`; use `mcp-update` before intentionally
  bumping them.
- The custom `agents` MCP server is read-only by default for task/config mutation. Set
  `AGENTS_MCP_ALLOW_MUTATION=1` only in sessions where MCP-triggered task runs or config syncs
  are intentionally allowed.
- Personal-assistant writes are controlled by `assistant/policy.md` and the shared
  `personal-actions-mcp` facade. It defaults to dry-run unless `PERSONAL_ACTIONS_DRY_RUN=0`,
  `PERSONAL_ACTIONS_PROVIDER`, and the provider credentials are configured.
- The PreToolUse guard hook is active here too; destructive commands stay blocked.
- Tools: see `Brewfile`. Languages via `mise` + `rustup`. VCS is jj-first (colocated on the laptop).
- New machine / full reference: see `ONBOARDING.md`.
