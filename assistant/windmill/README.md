# Windmill Backend for Personal Actions

Windmill is the preferred open-source backend for live Slack, Gmail, Calendar, and Drive actions.
Claude and Codex still talk only to `personal-actions-mcp`; Windmill receives the single webhook
behind that facade.

```text
Claude / Codex
        |
        v
personal-actions-mcp
        |
        v
Windmill webhook
        |
        v
Slack / Gmail / Calendar / Drive resources
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

Self-hosted Windmill does not show Slack/Gmail/GCal under "OAuth APIs" until OAuth client
configuration exists at the instance level. Create provider credentials first:

- Google OAuth web client with the needed APIs enabled:
  - `http://localhost:8790/oauth/callback/gmail`
  - `http://localhost:8790/oauth/callback/gcal`
  - `http://localhost:8790/oauth/callback/gdrive`
  - `http://127.0.0.1:8765/callback`
  - `http://127.0.0.1:8766/callback`
  - `http://127.0.0.1:8767/callback`
  - `http://127.0.0.1:8768/callback`
- Slack app OAuth client/secret, or use Windmill's Slack CLI path with a pre-minted token. Slack
  search requires a token with Slack search/read permissions such as `search:read`; channel history
  reads require the relevant conversation history scopes.

Store the OAuth client values outside the repo:

```bash
cp ~/.config/agents/assistant/windmill/oauth.env.example \
  ~/.config/agents-secrets/windmill-oauth.env
zed ~/.config/agents-secrets/windmill-oauth.env
windmill-oauth-configure
```

Then create OAuth resources:

   - Slack resource, for send/search.
   - Gmail or Google Workspace resource, for search/read/send.
   - Google Calendar resource, for list/create/update.
   - Google Drive resource, for file search.

The handler defaults expect these resource paths:

- `u/admin/slack`
- `u/admin/gmail`
- `u/admin/gcal`
- `u/admin/gdrive`
- `u/admin/work_gmail`
- `u/admin/work_gcal`
- `u/admin/work_gdrive`

If you use different paths, edit the script defaults in Windmill.

The Windmill UI may generate names like `u/admin/charismatic_gmail`. Create stable aliases at
the paths above so Claude and Codex keep using the same resource contract.

```bash
windmill-link-personal-resources
```

After connecting a second Gmail/GCal account, link the work aliases:

```bash
windmill-link-personal-resources --include-work
```

Current support:

- Slack send/search is live when the Slack resource has the needed scopes. For self-tests, send to
  the user's own Slack user id/DM only.
- Gmail search/read/send is live after enabling the Gmail API in the Google Cloud project.
- Calendar list/create/update is live after enabling the Google Calendar API.
- Drive search is live after enabling the Google Drive API and connecting a `gdrive` resource.
- Gmail draft uses a local compose-scope token because Windmill CE's built-in `gmail` OAuth grants
  `gmail.send`. To enable draft creation, add `http://127.0.0.1:8765/callback` to the Google OAuth
  client's authorized redirect URIs, then run:

```bash
personal-actions-google-compose-auth
```

For the work account, also add `http://127.0.0.1:8766/callback` to the Google OAuth client and run:

```bash
personal-actions-google-compose-auth --account work
```

- Gmail trash uses a separate local `gmail.modify` token and moves only one exact message id to
  Trash. It never calls Gmail's permanent delete endpoint. Add `http://127.0.0.1:8767/callback`
  and `http://127.0.0.1:8768/callback` to the Google OAuth client, then run:

```bash
personal-actions-google-modify-auth
personal-actions-google-modify-auth --account work
```

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

Or run the live canary helper:

```bash
personal-actions-canary --yes
personal-actions-canary --yes --account work --email kaelan@vizcom.com
```

## Operations

```bash
windmill-status
windmill-logs
windmill-down
```

Do not add Windmill MCP to `mcp.json` yet. The narrow local facade is the agent-facing tool surface.
