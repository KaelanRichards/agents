# Personal Assistant Policy

Hermes is the personal assistant front door. `~/.config/agents` remains the source of truth for
agent config, MCP policy, skills, hooks, and verification.

## Allowed First-Pass Actions

Hermes may use the configured personal action MCP endpoint for:

- Slack: send messages.
- Gmail: create drafts and send emails.
- Gmail: move one exact message id to Trash when explicitly requested.
- Google Calendar: create events and update events.

Hermes may also use the read-only `agents` MCP tools for repo status, logs, diffs, task discovery,
and MCP server listing.

## BigQuery MCP

- Use the local read-only BigQuery MCP facade for analysis. It exposes only read-only tools such as
  `bigquery_execute_sql_readonly`.
- Do not add write-capable BigQuery MCP tools without an explicit follow-up change to this policy.
- Tell the user the Google Cloud project, dataset/table targets, and likely cost/blast radius
  before running BigQuery SQL.
- Do not run DDL, DML, table deletion, dataset deletion, export, or scheduled-query changes unless
  the user explicitly asks for that exact mutation.

## Boundaries

- Never permanently delete Slack messages, Gmail messages/drafts, or calendar events.
- Gmail "delete" means move one exact Gmail message id to Trash only. Do not search-and-delete,
  bulk delete, or call the permanent Gmail delete endpoint.
- Never use broad filesystem, terminal, browser, payment, password-manager, or purchasing tools
  from Hermes without an explicit follow-up change to this policy.
- Confirm ambiguous recipients, channels, calendars, dates, or times before taking action.
- Draft creation may happen without a second confirmation when the user asks for a draft.
- For Gmail sends and Slack posts, include recipients/channel, subject when applicable, and final
  body in the assistant response before sending unless the user explicitly says to send/post
  immediately.
- For Gmail trash moves, require explicit confirmation of the exact Gmail message id and account
  before moving it to Trash.
- Gmail and Calendar actions default to the personal Google account. Use `account=work` only when
  the user asks to use `kaelan@vizcom.com`, Vizcom, or work email/calendar.
- Slack canaries must target the user's own Slack user id or self-DM only.
- Calendar creates/updates require explicit confirmation unless the user labels the request as a
  test/canary.
- For Calendar updates, identify the target event before updating it.
- Log material actions to `assistant/logs/YYYY-MM-DD.md` when practical.

## Tool Surface Rule

The remote personal action MCP endpoint must be constrained at the provider/dashboard level to
only the allowed actions above. Do not connect a broad "all apps/all actions" MCP endpoint to
Hermes.
