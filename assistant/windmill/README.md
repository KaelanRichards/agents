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
```

Open `http://localhost:8790`. Change the initial admin password immediately.

The stack is defined in `stacks/windmill/` and binds only to `127.0.0.1`. Runtime secrets live in
`~/.config/agents-secrets/windmill.env`, outside the repo. Keep it local until the webhook path is
proven.

## Windmill Setup

1. Create OAuth resources:
   - Slack resource, for `chat.postMessage`.
   - Gmail or Google Workspace resource, for draft/send.
   - Google Calendar resource, for event create/update.
2. Create a TypeScript script named `personal_actions_handler`.
3. Paste `assistant/windmill/personal_actions_handler.ts`.
4. Set these script defaults/arguments:
   - `hmac_secret`: value from `~/.config/agents-secrets/personal-actions.env`.
   - `slack_resource_path`: your Slack resource path.
   - `gmail_resource_path`: your Gmail resource path.
   - `calendar_resource_path`: your Google Calendar resource path.
5. Create a webhook-specific token for that script.
6. Use the synchronous `run_wait_result` webhook URL.

For localhost HTTP, configure the local facade with:

```bash
PERSONAL_ACTIONS_ALLOW_HTTP=1 personal-actions-configure --url "http://localhost:8790/api/w/<workspace>/jobs/run_wait_result/..." --live
```

Then edit `~/.config/agents-secrets/personal-actions.env` and replace
`PERSONAL_ACTIONS_WEBHOOK_TOKEN` with the Windmill webhook-specific token.

## Verify

```bash
personal-actions-check
```

Then run canaries in this order:

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
