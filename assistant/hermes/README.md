# Hermes Personal Assistant Profile

Hermes is installed separately under `~/.hermes/hermes-agent`. This repo manages the operating
policy and generated Hermes config.

## Sync

```bash
hermes-sync
```

This writes `~/.hermes/config.yaml` with:

- read-only `agents` MCP tools
- a disabled `personal_actions` MCP endpoint until configured
- context files from `AGENTS.md` and `assistant/`

## Enable Slack/Gmail/Calendar Writes

Create a constrained remote MCP endpoint with only these actions:

- Slack: send message
- Gmail: create draft
- Gmail: send email
- Google Calendar: create event
- Google Calendar: update event

Recommended providers are Zapier MCP or Pipedream MCP because they handle OAuth and app-specific
scopes outside this repo. Do not use an all-actions endpoint.

Then set:

```bash
export HERMES_PERSONAL_ACTIONS_MCP_URL="https://..."
hermes-sync
```

Restart Hermes or run `/reload-mcp` in Hermes.

## Use

```bash
hermes
```

Ask Hermes to list available MCP tools after sync. It should see `agents_readonly` and, once the
URL is configured, the constrained personal action tools.

## Boundary

Hermes bundled skills live under `~/.hermes/skills` and are intentionally separate from the shared
Claude/Codex skills under `~/.config/agents/skills`.
