# Onboarding — the agent environment

One repo (`~/.config/agents`) that makes **Claude Code and Codex CLI behave identically** on any
machine, from a single source of truth for instructions, MCP servers, subagents, skills, and hooks.

## Rebuild from scratch
```bash
git clone git@github.com:KaelanRichards/agents.git ~/.config/agents
bash ~/.config/agents/bootstrap.sh    # toolbelt + languages + sync (Linux/macOS)
agents-doctor                         # verify everything is healthy
```
Then authenticate: `claude` (`/login`), `codex login`, `gh auth login`, set `GITHUB_PAT`, and
run `mcp-auth plan` for OAuth-backed hosted MCPs you want on the host.

## Architecture
- **Instructions** — `AGENTS.md` is canonical; symlinked to `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`.
- **MCP servers** — `mcp.json` is canonical; `mcp-sync` generates Claude JSON + Codex TOML.
- **Subagents / skills / hooks** — `agents/`, `skills/`, `hooks/`; `agents-sync` generates both tools' configs.
- **VCS** — jj-first, colocated (git / gh still work underneath).
- **Remote** — `provision.sh` / `teardown.sh` (Hetzner VM up/down); `bootstrap.sh` reproduces the env; `flake.nix` is the pinned, hermetic alternative toolbelt.
- **Own tools as MCP** — `mcp-servers/agents/server.py` (launched by `bin/agents-mcp`).

## Daily commands
| Command | Purpose |
|---|---|
| `mcp-sync add <n> -- <cmd>` / `add-http <n> <url> [ENV]` | add an MCP server (both tools) |
| `mcp-auth login <server>` | OAuth login for mcp-remote-backed MCPs, cached in `~/.mcp-auth` |
| `mcp-auth vm-login <server> <host>` | authenticate a VM MCP from your laptop browser over an SSH callback tunnel |
| `mcp-auth plan` / `mcp-auth status` | setup/status for OAuth-backed remote MCPs per host |
| `agents-sync` | regenerate subagents / skills / hooks |
| `agents-doctor` | full health check |
| `agents-status` | read-only overview: VMs, health, MCP, CI/PRs, sessions |
| `agents-reconcile --apply` | converge a VM/plain git clone to `origin/main`, preserving drift in git stash |
| `dash` | interactive TUI dashboard (live panels + action keys) |
| `dashweb` | HTML dashboard (local :8787; VM always-on via `serve` + Tailscale) |
| `serve` | (VM) run webdash always-on + expose via `tailscale serve` |
| `swarm "task" ...` | parallel agents across jj workspaces |
| `wt new <name>` | one isolated workspace |
| `obs up` | start the observability stack |

## Extending
- **New MCP server:** `mcp-sync add …` (never hand-edit `~/.claude.json` or Codex's managed block).
  If it is an OAuth remote and clients do not all handle native OAuth cleanly, prefer a
  `mcp-remote` stdio bridge and add/maintain its operational auth contract in `mcp.auth.json`.
- **New tool:** add to `Brewfile` (and `flake.nix`), commit — bootstrap and CI pick it up.
- **New subagent / skill:** drop into `agents/` or `skills/`, run `agents-sync`.
- **New agent (e.g. Gemini CLI):** add a generator branch to `mcp-sync`/`agents-sync` for its
  config format and symlink its instruction file to `AGENTS.md`.

## Maintenance — where the moving parts live
- **Install URLs** (claude / codex / Homebrew / Nix) live in `bootstrap.sh` — one place to fix if a vendor URL moves.
- **Pins:** `flake.lock` pins the Nix toolbelt; the `update-flake` workflow + Dependabot open PRs to keep deps fresh and CI-validated.
- **CI** (`.github/workflows/ci.yml`) lints every push; weekly it runs the bootstrap smoke test, `agents-doctor`, the sync round-trip test, and `nix flake check`.
- **Drift detection:** run `agents-doctor` anytime — it flags missing tools, broken symlinks, MCP mismatch, and agent-CLI version changes that may shift config formats.
