# agents — portable agent environment (laptop + always-on VM)

Single source of truth for **Claude Code + Codex CLI**: instructions (`AGENTS.md`), MCP servers
(`mcp.json`), subagents/skills/hooks, helper scripts (`bin/`), shell env (`zsh/agents.env.zsh`
for all shells plus `zsh/agents.zsh` for interactive extras), dashboards, observability, CI,
and a `bootstrap.sh` that reproduces the whole thing on a fresh box.

The shared MCP set includes official OAuth-backed Linear, Sentry, Notion, Granola, Cloudflare,
and Slack MCPs bridged through `mcp-remote` or a narrow wrapper, the official Datadog US5 remote
MCP server, and a local read-only BigQuery facade (`bigquery-mcp`) that uses the machine's
existing `gcloud`/`bq` auth.
The Datadog endpoint is pinned to
`https://mcp.us5.datadoghq.com/api/unstable/mcp-server/mcp?toolsets=core,apm,error-tracking,software-delivery`.
The active BigQuery project is `vizcom-web`; it needs the BigQuery API enabled and MCP Tool User,
BigQuery Job User, and BigQuery Data Viewer for the signed-in identity.

## Provision an always-on VM (so you can close your laptop)

**Option A — one command (Hetzner):**
```bash
brew install hcloud
export HCLOUD_TOKEN=...                 # console.hetzner.cloud -> API Tokens
bash ~/.config/agents/provision.sh     # creates the VM and bootstraps it
```
Defaults: `VM_TYPE=cax11` (ARM, EU-only) at `VM_LOCATION=fsn1`. Other tunables: `VM_USER`,
`AGENTS_REPO`. For US/x86 export `VM_TYPE=cpx21 VM_LOCATION=ash` before running. The script
prints the planned `(type / image / location)` before it calls `hcloud server create`.

**Option B — any provider, by hand:**
1. Provision Ubuntu 24.04, ≥ 2 GB RAM (Hetzner / DigitalOcean / Fly); add your SSH key.
2. On the VM: `git clone <repo-url> ~/.config/agents && bash ~/.config/agents/bootstrap.sh`

**Then authenticate** on the VM: `claude` -> `/login`, `codex login`, `gh auth login`,
and set `GITHUB_PAT` (GitHub MCP). For OAuth-backed hosted MCPs, run `mcp-auth plan`, then
`mcp-auth login <server>` once per host; every synced stdio client on that host reuses
`~/.mcp-auth`. For a VM, run `mcp-auth vm-login <server> <vm-host>` from the laptop so your
local browser can complete the VM-side OAuth callback.
Slack's official MCP additionally needs host-local `SLACK_MCP_CLIENT_ID` and
`SLACK_MCP_CLIENT_SECRET`, or `SLACK_MCP_CLIENT_INFO_FILE`, because Slack does not support Dynamic
Client Registration. The Slack app must allow the local callback URL
`http://127.0.0.1:3339/oauth/callback`.
Run `agents-doctor` to confirm it's healthy.

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

All surfaces read the same data (machines+cost, health, MCP, CI/PRs, sessions, queue, approvals)
from one typed backend — **`agentd`** (`web/agentd.py`), which imports `scripts/agent_control.py`
directly so the ledger + event log fire identically no matter which surface triggers an action.
Pick a surface by context:
- **`agents-status`** — one-shot text overview.
- **`dash`** — live TUI control center (panels + keys: `r` refresh · `s` sync · `d` doctor · `g` grafana · `q` quit).
- **`dashweb`** — live HTML control center: SSE cards, streamed action logs, control buttons
  (sync/doctor/provision/teardown/reboot, MCP add/remove), embedded Grafana + terminal.
- **desktop app** (`desktop/`) — native macOS Tauri app: tray status pill, native approval
  notifications, Keychain-stored tokens, PTY attach. See `desktop/README.md`.

> Maintenance note: four surfaces over one data model is a known cost, kept honest by the single
> `agentd` backend. The **desktop app is the primary macOS surface** and **`dashweb` is the primary
> remote/phone surface** (tailnet access, mutation controls). `dash` and `agents-status` stay as
> quick local views. Before adding a feature, put it in the `agentd` read model / action set first
> (so every surface inherits it), then wire the UI — preferring the desktop app and `dashweb`.

```bash
dashweb     # local: http://localhost:8787 (read-only without WEBDASH_TOKEN)
```
Panel prerequisites: Grafana panel needs `obs up`; terminal panel needs `ttyd -p 7681 -W zsh`.
Dashboard mutation controls (`sync`, `doctor`, queue/approval actions, MCP add/remove, VM actions)
require `WEBDASH_TOKEN` and same-origin CSRF headers even on localhost.

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

If the VM has local drift, use `agents-reconcile --apply` instead. It stashes tracked and
untracked changes, resets the clone to `origin/main`, relinks helpers, and regenerates MCP/agent
configs. On an always-on VM, `agents-reconcile install-user-timer` installs the self-healing user
timer.

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
- **`agents-reconcile`** — VM/plain-git self-healing sync: stash drift, reset to `origin/main`,
  regenerate MCP/agent config, and optionally install a periodic user timer.
- **Agent control plane** — local orchestration primitives layered on top of jj, tmux, MCP, and
  the shared profile/policy model:
  - `agent-profile list|validate|compile` manages canonical permission profiles in `profiles/`
    and writes disposable generated artifacts under `generated/profiles/`.
  - `agentp <profile>` / `agentp --codex <profile>` launches a coding agent **under** a profile as
    a real boundary, composing each harness's *native* enforcement (it does not reimplement it):
    - **Claude**: the profile's MCP subset via `--strict-mcp-config` (only those servers load), a
      compiled `--settings` file with deny/ask rules **and a native OS Bash sandbox**
      (`sandbox.*`: writable roots + `denyRead` of `~/.ssh`/`~/.aws`/secrets), and `AGENTS_PROFILE`
      so the `profile-broker` PreToolUse hook enforces per-tool read/write policy that settings
      alone can't express (e.g. allow Datadog reads, deny Datadog writes on the same server).
    - **Codex**: native `--sandbox` + `--ask-for-approval` derived from the profile's risk/mode.
    - `agentp list` shows the profiles. (Gemini/Qwen/OpenCode artifacts are compiled for reference.)
  - `agent-ledger record|list|show|verify` stores append-only run events under gitignored
    `state/runs/`. Entries form a SHA-256 hash chain; `agent-ledger verify` confirms it is
    tamper-evident (also checked by `agents-doctor`).
  - `agentq add|list|show|start|worker` queues background agent work into isolated jj workspaces.
    On an always-on VM, install `systemd/agentq-worker.{service,timer}` as user units and enable
    the timer to poll queued work every minute.
  - `agent-approve request|list|show|approve|reject|expire` manages the local approval inbox.
    Requests carry a TTL (default 24h, `--ttl-hours`) and auto-expire instead of lingering pending.
  - `agent-eval list|run` runs small local eval tasks from `evals/tasks/`, including
    `policy-enforcement` (adversarial broker checks: synonym evasion, fail-closed effects,
    tainted-context writes, per-profile boundaries).
  - `agent-broker` holds the policy logic (effect classification from an authoritative registry,
    fail-closed for unknown tools; provenance rule: a mutation with `context_tainted=true` is
    forced to confirm and refused on high/critical profiles). It runs in **two** places: the MCP
    facade (advisory, for interactive queries) and — load-bearing — the `profile-broker` PreToolUse
    **hook** (`hooks/profile-broker.sh`), which the model cannot route around. Same code, both paths.
- **`just ci-local`** — local verification loop: shell scripts, JSON locks, sync round-trip,
  agent-system contract checks, dashboard smoke test, `gitleaks`, and `agents-doctor`.
- **`skills-audit` / `skills-update`** — review vendored skill provenance and executable surface,
  then report upstream drift without modifying files. `skills.lock.json` is the source of truth.
- **`mcp-update`** — report npm drift for pinned stdio MCP packages without modifying `mcp.json`.
- **`mcp-auth`** — status/setup helper for OAuth-backed remote MCPs. It validates
  `mcp.auth.json`, runs `mcp-remote` login probes, prints the clean VM auth plan, and checks
  local client status without exporting tokens.
- **`hermes-sync`** — generate the managed Hermes personal-assistant profile at
  `~/.hermes/config.yaml`. Hermes uses the shared local `personal-actions-mcp` facade for Slack,
  Gmail, and Calendar writes plus read-only `agents` MCP tools. Gmail trash is recoverable only:
  one exact message id moved to Trash, never permanent or bulk deletion.
- **`windmill-up` / `windmill-status` / `windmill-down`** — manage the local open-source Windmill
  backend for live personal actions. See `assistant/windmill/README.md`.
- **`obs up|down|on|off|status`** — local OpenTelemetry → Prometheus → Grafana stack for agent
  cost/usage. `obs on`/`obs up` drop a `.telemetry-on` marker that `zsh/agents.env.zsh` reads, so
  every agent shell exports `OTEL_*` automatically (no per-session `obs env`). On the VM, `serve`
  installs `systemd/otel-stack.service` and turns telemetry on so cost/usage accrues 24/7.
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
  `PERSONAL_ACTIONS_PROVIDER`, and the provider credentials are configured. Use
  `personal-actions-configure` to write the local gitignored env file, see
  `assistant/personal-actions-webhook.md` for the backend contract, and run `personal-actions-check`
  for a non-mutating reachability test.
- The PreToolUse guard hook is active here too; destructive commands stay blocked.
- Tools: see `Brewfile`. Languages via `mise` + `rustup`. VCS is jj-first (colocated on the laptop).
- New machine / full reference: see `ONBOARDING.md`.
