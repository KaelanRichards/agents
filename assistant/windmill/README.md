# Windmill Backend for Personal Actions

Windmill is the preferred open-source backend for live Slack, Gmail, and Calendar writes. Claude,
Codex, and Hermes still talk only to `personal-actions-mcp`; Windmill receives the single webhook
behind that facade.

```text
Claude / Codex / Hermes
        |
        v
personal-actions-mcp
        |
        v
Windmill webhook
        |
        v
Slack / Gmail / Calendar resources
```

## Start

```bash
windmill-up
windmill-status
windmill-bootstrap
```

Open `http://localhost:8790`. `windmill-bootstrap` rotates the default admin password and stores
the local credentials in `~/.config/agents-secrets/windmill-admin.env`.

The stack is defined in `stacks/windmill/` and binds only to `127.0.0.1`. Runtime secrets live in
`~/.config/agents-secrets/windmill.env`, outside the repo. Keep it local until the webhook path is
proven.

## Windmill Setup

`windmill-bootstrap` creates:

- Workspace: `personal`
- Script: `f/personal_actions/handler`
- Script webhook URL in `~/.config/agents-secrets/personal-actions.env`
- Windmill secret variables for the local bearer/HMAC values

## OAuth Resources

Create OAuth resources:

   - Slack resource, for `chat.postMessage`.
   - Gmail or Google Workspace resource, for draft/send.
   - Google Calendar resource, for event create/update.

The handler defaults expect these resource paths:

- `u/admin/slack`
- `u/admin/gmail`
- `u/admin/gcal`

If you use different paths, edit the script defaults in Windmill.

## Verify

```bash
personal-actions-check
```

This should return `{"ok": true, "write": false, "action": "health_check"}`.

After OAuth resources are connected, set `PERSONAL_ACTIONS_DRY_RUN=0` in
`~/.config/agents-secrets/personal-actions.env`. Then run canaries in this order:

1. Gmail draft to yourself.
2. Calendar event on a test calendar.
3. Slack message to a private test channel.
4. Gmail send to yourself.
5. Calendar update on the test event.

## Operations

```bash
windmill-status
windmill-logs
windmill-down
```

Do not add Windmill MCP to `mcp.json` yet. The narrow local facade is the agent-facing tool surface.
