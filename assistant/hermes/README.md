# Hermes Personal Assistant Profile

Hermes is installed separately under `~/.hermes/hermes-agent`. This repo manages the operating
policy and generated Hermes config.

## Sync

```bash
hermes-sync
```

This writes `~/.hermes/config.yaml` with:

- read-only `agents` MCP tools
- the shared local `personal_actions` MCP facade
- context files from `AGENTS.md` and `assistant/`

## Enable Slack/Gmail/Calendar Writes

Hermes, Claude, and Codex all use the same `personal-actions-mcp` facade. It exposes only these
actions:

- Slack: send message
- Gmail: create draft
- Gmail: send email
- Google Calendar: create event
- Google Calendar: update event

The facade defaults to dry-run. To route live actions through a constrained automation endpoint,
set:

```bash
personal-actions-configure --url "https://..." --live
hermes-sync
```

Recommended webhook backends are Zapier or Pipedream because they handle OAuth and app-specific
scopes outside this repo. Do not use an all-actions endpoint.
Use `assistant/personal-actions-webhook.md` for the required request contract and Pipedream
validation step. Run `personal-actions-check` before the first live write.

For local Gmail send and Calendar create only, `PERSONAL_ACTIONS_PROVIDER=google_workspace_cli`
can call Hermes' bundled Google Workspace helper. Draft creation, Slack send, and Calendar update
still require the webhook provider.

Restart Hermes or run `/reload-mcp` in Hermes after changing the config or environment.

Live canaries are available through:

```bash
personal-actions-canary --yes
```

Gmail draft creation requires the separate compose-scope local OAuth setup:

```bash
personal-actions-google-compose-auth
```

## Use

```bash
hermes
```

Ask Hermes to list available MCP tools after sync. It should see `agents_readonly` and the five
constrained personal action tools. With no live provider configured, calls return dry-run responses
and write redacted audit logs under `assistant/logs/personal-actions/`.

## Boundary

Hermes bundled skills live under `~/.hermes/skills` and are intentionally separate from the shared
Claude/Codex skills under `~/.config/agents/skills`.
