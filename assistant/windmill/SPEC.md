# Spec: Windmill Personal Actions Backend

## Outcome

Run an open-source Windmill instance as the preferred local backend for `personal-actions-mcp`.
Claude, Codex, and Hermes continue to see only the five shared local tools; Windmill receives one
authenticated webhook and dispatches to Slack, Gmail, and Google Calendar resources.

## Scope

- **In:** Local Docker Compose stack for Windmill bound to localhost.
- **In:** Helper scripts to start, stop, inspect, and print setup guidance.
- **In:** A Windmill TypeScript script template that validates the existing personal-actions
  contract: HMAC, timestamp skew, idempotency key, allowlisted actions, and payload keys.
- **In:** Documentation for first-run Windmill setup, OAuth resource creation, webhook URL/token
  configuration, and canary testing.
- **Out:** Public internet exposure, Tailscale serving, automatic browser OAuth, broad Windmill MCP
  exposure to Claude/Codex/Hermes, and committing any secrets.

## Constraints

- Keep Windmill localhost-only until OAuth resources and webhook auth are proven.
- Use Windmill webhook-specific bearer tokens as the `PERSONAL_ACTIONS_WEBHOOK_TOKEN`.
- Use `PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET` for app-level request signing.
- Do not expose Windmill MCP to agents by default.
- Store local secrets outside this repo under `~/.config/agents-secrets`.
- Use OrbStack/Docker Compose when available, but keep the repo usable if Docker is stopped.

## Tasks

- [x] T1 — Stack files: `stacks/windmill/docker-compose.yml`, `stacks/windmill/.env.example`.
- [x] T2 — Helper scripts: `bin/windmill-up`, `bin/windmill-down`, `bin/windmill-status`,
  `bin/windmill-logs`, `bin/windmill-setup`.
- [x] T3 — Windmill script template:
  `assistant/windmill/personal_actions_handler.ts`.
- [x] T4 — Documentation: `assistant/windmill/README.md`, main README references.
- [x] T5 — Verification: shellcheck, JSON/TOML/YAML validation where applicable, local CI.

## Verification

- `shellcheck -S error -x bin/windmill-*`
- `yq -e . stacks/windmill/docker-compose.yml`
- `just ci-local`
- If Docker is available: `windmill-up`, `windmill-status`, then open `http://localhost:8790`.
- After creating the Windmill script and webhook token:
  `personal-actions-configure --url "http://localhost:8790/api/w/<workspace>/jobs/run_wait_result/..." --live`
  with `PERSONAL_ACTIONS_ALLOW_HTTP=1` only for localhost.
